"""Phase 4.6 -- the metrics surface (M4-4.6-FR-010..012, §12, AC-04, AC-11).

**Prometheus text exposition, pulled, not pushed.** A metrics value is
state-shaped ("how many executions failed in the last hour, by provider"), and
the natural way to publish state is to let a scraper read it on its own clock.
Push (OTLP metrics) would add a second export loop with its own backpressure
problem for no benefit -- the collector already knows how to scrape. Traces are
different (event-shaped, and the platform is the only thing that has them at the
moment they happen), which is why *those* are pushed. So: spans push over OTLP,
metrics are scraped over ``GET /metrics``.

**Every label goes through :func:`metric_label_set`, which reuses 4.1's
denylist.** ``execution_id``, an email, a prompt -- anything in
:data:`~app.observability.attributes.HIGH_CARDINALITY_ATTRIBUTES` or
:data:`~app.observability.attributes.SENSITIVE_ATTRIBUTES` -- raises rather than
becoming a series. The allowed set is 4.1's :data:`METRIC_DIMENSIONS` plus a
tiny, explicitly-declared extension for the two behavioral-finding enums, each
of which is a closed vocabulary this codebase owns. A structural test asserts no
metric can emit anything else.

**Derived from existing rows, computing nothing new.** The numbers come from
``agent_executions`` (counts, outcomes, latency, spend) and
``behavioral_findings`` (signal states) with ordinary ``GROUP BY``. No new
metric-source table, no per-execution series -- the grouping keys are all
bounded.

**Tenant-isolated.** Every domain query leads with ``organization_id``; the
endpoint returns the caller's organization's numbers and no one else's. The
process-level export-health gauges carry no tenant data at all.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Numeric, cast, func, select
from sqlalchemy.orm import Session

from app.models.runtime import (
    AgentDeployment,
    AgentExecution,
    AgentVersion,
    BehavioralFinding,
)
from app.observability.attributes import (
    HIGH_CARDINALITY_ATTRIBUTES,
    METRIC_DIMENSIONS,
    SENSITIVE_ATTRIBUTES,
    MetricCardinalityError,
)
from app.telemetry_export.health import exporter_health

#: 4.6's declared extension to 4.1's bounded dimension set. Two enums the
#: behavioral engine owns -- ``signal_type`` is the seven-member
#: ``SIGNAL_TYPES`` tuple, ``state`` is the five-member CHECK constraint on
#: ``behavioral_findings.state``. Declared here, not added to
#: ``METRIC_DIMENSIONS``, because they are meaningful only on the behavioral
#: metric and must not become legal labels on an execution counter.
_EXPORT_BOUNDED_DIMENSIONS: frozenset[str] = frozenset({"signal_type", "state", "outcome"})

_ALLOWED_LABELS: frozenset[str] = METRIC_DIMENSIONS | _EXPORT_BOUNDED_DIMENSIONS

_DEFAULT_WINDOW = timedelta(hours=1)
_NAME_RE = re.compile(r"[^a-zA-Z0-9_]")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def metric_label_set(**labels) -> dict[str, str]:
    """Build a label dict for a 4.6 metric, rejecting anything unbounded.

    The rejection order matters: sensitive first (a name that is a person or a
    payload can never be a label, cardinality irrelevant), then high-cardinality
    (an identity belongs on a trace), then "not a declared dimension". ``None``
    values drop out -- an absent dimension is absent, not the string "None"."""
    out: dict[str, str] = {}
    for name, value in labels.items():
        if name in SENSITIVE_ATTRIBUTES:
            raise MetricCardinalityError(
                f"{name!r} is a sensitive attribute and can never be a metric label (§12)."
            )
        if name in HIGH_CARDINALITY_ATTRIBUTES:
            raise MetricCardinalityError(
                f"{name!r} is a high-cardinality identity: it belongs on a trace, not a "
                f"metric label (§12). Allowed: {sorted(_ALLOWED_LABELS)}."
            )
        if name not in _ALLOWED_LABELS:
            raise MetricCardinalityError(
                f"{name!r} is not a declared metric dimension. Allowed: "
                f"{sorted(_ALLOWED_LABELS)}."
            )
        if value is None:
            continue
        out[name] = str(value)
    return out


def _model_category(model: str | None) -> str:
    """4.1's rule (``SemanticAttributes.model_category``): the vendor family,
    the segment before the first separator. Unbounded ``model`` never becomes a
    label; its bounded category does."""
    if not model:
        return "unknown"
    head = re.split(r"[-:/@]", str(model), maxsplit=1)[0]
    return head.lower() or "unknown"


class _Sample:
    __slots__ = ("name", "labels", "value")

    def __init__(self, name: str, labels: dict[str, str], value: float) -> None:
        self.name = name
        self.labels = labels
        self.value = value


class MetricsRenderer:
    """Collects samples and renders Prometheus text exposition format 0.0.4."""

    def __init__(self) -> None:
        self._help: dict[str, tuple[str, str]] = {}
        self._samples: list[_Sample] = []

    def family(self, name: str, kind: str, help_text: str) -> None:
        self._help[name] = (kind, help_text)

    def add(self, name: str, value: float, **labels) -> None:
        self._samples.append(_Sample(name, metric_label_set(**labels), float(value)))

    def render(self) -> str:
        lines: list[str] = []
        by_name: dict[str, list[_Sample]] = {}
        for sample in self._samples:
            by_name.setdefault(sample.name, []).append(sample)
        for name, (kind, help_text) in self._help.items():
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} {kind}")
            for sample in by_name.get(name, []):
                lines.append(f"{name}{_fmt_labels(sample.labels)} {_fmt_value(sample.value)}")
        return "\n".join(lines) + "\n"


def _fmt_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    inner = ",".join(
        f'{_NAME_RE.sub("_", k)}="{_escape(v)}"' for k, v in sorted(labels.items())
    )
    return "{" + inner + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _fmt_value(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return repr(value)


class MetricsCollector:
    """Builds the exposition for one organization from existing rows."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def render(self, organization_id: uuid.UUID, *, window: timedelta | None = None) -> str:
        window = window or _DEFAULT_WINDOW
        since = _now() - window
        r = MetricsRenderer()
        self._executions(r, organization_id, since)
        self._behavioral(r, organization_id, since)
        _export_health_metrics(r)
        return r.render()

    # ------------------------------------------------------------------ #
    def _executions(self, r: MetricsRenderer, org: uuid.UUID, since: datetime) -> None:
        r.family("act_runtime_executions", "gauge",
                 "Executions that reached a terminal state in the window, by outcome.")
        r.family("act_runtime_execution_duration_ms_sum", "gauge",
                 "Summed execution duration (ms) in the window.")
        r.family("act_runtime_execution_duration_ms_count", "gauge",
                 "Count of executions contributing to the duration sum.")
        r.family("act_runtime_spend_usd", "gauge",
                 "Summed real (non-estimated) execution cost in USD in the window.")

        prov = AgentVersion.model_configuration["provider"].astext
        model = AgentVersion.model_configuration["model"].astext
        rows = self.db.execute(
            select(
                AgentExecution.status.label("status"),
                AgentDeployment.environment.label("environment"),
                prov.label("provider"),
                model.label("model"),
                func.count(AgentExecution.id).label("n"),
                func.coalesce(func.sum(AgentExecution.duration_ms), 0).label("dur"),
                func.coalesce(
                    func.sum(
                        cast(func.coalesce(AgentExecution.cost_amount, 0), Numeric(18, 8))
                    ), 0
                ).label("cost"),
            )
            .join(AgentVersion, AgentVersion.id == AgentExecution.agent_version_id, isouter=True)
            .join(AgentDeployment, AgentDeployment.id == AgentExecution.deployment_id, isouter=True)
            .where(AgentExecution.organization_id == org)
            .where(AgentExecution.completed_at.is_not(None))
            .where(AgentExecution.completed_at >= since)
            .group_by(AgentExecution.status, AgentDeployment.environment, prov, model)
        ).all()

        # Fold the raw (provider, model) rows into (provider, model_category):
        # the model string never becomes a label, only its family does.
        folded: dict[tuple, list[float]] = {}
        for row in rows:
            key = (
                (row.environment or "unknown"),
                (row.status or "UNKNOWN"),
                (row.provider or "unknown"),
                _model_category(row.model),
            )
            acc = folded.setdefault(key, [0.0, 0.0, 0.0])
            acc[0] += float(row.n)
            acc[1] += float(row.dur)
            acc[2] += float(row.cost)

        for (environment, status, provider, model_category), (n, dur, cost) in folded.items():
            common = dict(environment=environment, provider=provider,
                          model_category=model_category)
            r.add("act_runtime_executions", n, status=status, **common)
            r.add("act_runtime_execution_duration_ms_sum", dur, status=status, **common)
            r.add("act_runtime_execution_duration_ms_count", n, status=status, **common)
            r.add("act_runtime_spend_usd", cost, status=status, **common)

    def _behavioral(self, r: MetricsRenderer, org: uuid.UUID, since: datetime) -> None:
        r.family("act_runtime_behavioral_findings", "gauge",
                 "Behavioral findings evaluated in the window, by signal type and state.")
        rows = self.db.execute(
            select(
                BehavioralFinding.signal_type,
                BehavioralFinding.state,
                func.count(BehavioralFinding.id).label("n"),
            )
            .where(BehavioralFinding.organization_id == org)
            .where(BehavioralFinding.evaluated_at >= since)
            .group_by(BehavioralFinding.signal_type, BehavioralFinding.state)
        ).all()
        for row in rows:
            r.add("act_runtime_behavioral_findings", float(row.n),
                  signal_type=row.signal_type, state=row.state)


def _export_health_metrics(r: MetricsRenderer) -> None:
    """Process-level exporter health as metrics (FR-022): an operator on a
    Prometheus dashboard sees export degradation without calling the health
    endpoint. No tenant data -- these are properties of this process."""
    snap = exporter_health.snapshot()
    r.family("act_telemetry_export_spans_exported_total", "counter",
             "Spans successfully handed to the collector since process start.")
    r.family("act_telemetry_export_spans_dropped_total", "counter",
             "Spans dropped by the bounded buffer since process start.")
    r.family("act_telemetry_export_batches_failed_total", "counter",
             "Export batch attempts that failed since process start.")
    r.family("act_telemetry_export_degraded", "gauge",
             "1 when the last export attempt failed, 0 otherwise.")
    r.family("act_telemetry_export_consecutive_failures", "gauge",
             "Consecutive failed export attempts.")
    r.add("act_telemetry_export_spans_exported_total", snap["spans_exported_total"])
    r.add("act_telemetry_export_spans_dropped_total", snap["spans_dropped_total"])
    r.add("act_telemetry_export_batches_failed_total", snap["batches_failed_total"])
    r.add("act_telemetry_export_degraded", 1 if snap["degraded"] else 0)
    r.add("act_telemetry_export_consecutive_failures", snap["consecutive_failures"])
