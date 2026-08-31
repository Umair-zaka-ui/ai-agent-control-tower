"""Phase 4.7 -- Service Level Indicators, computed from real runtime rows
(ACT-SRS-M4 §3.6, M4-4.7-FR-001; mandatory report #2).

**Where the numbers come from, and why not the 4.6 metrics surface.** The 4.6
`/metrics` endpoint exposes *windowed gauges* -- "executions in the last hour,
by provider" -- derived at scrape time and rounded to bounded-cardinality
dimensions. That is the right shape for a Prometheus dashboard and the wrong
shape for an SLO, which needs an exact count over an *SLO-defined* window
(``1h`` / ``24h`` / ``7d`` / ``30d``) and a precise percentile. So every SLI
here reads ``agent_executions`` / ``tool_calls`` directly, with the same
tenant-leading, index-backed aggregation 3.5's health engine and 4.5's
behavioral engine already use over the same tables. The 4.6 metrics surface and
this share a *source of truth* (the domain rows), not a query.

**The six SLIs, and their exact predicates:**

| SLI | Numerator (bad) | Denominator | Direction | Unit |
|---|---|---|---|---|
| ``success_rate`` | non-``SUCCEEDED`` terminal | terminal executions | higher better | ratio |
| ``timeout_rate`` | ``TIMED_OUT`` | terminal executions | lower better | ratio |
| ``provider_error_rate`` | ``error_code`` in the 5.7a.4 taxonomy | terminal executions | lower better | ratio |
| ``tool_failure_rate`` | failed tool calls (5.6a.2 predicate) | tool calls | lower better | ratio |
| ``latency_p95`` | executions over the target | terminal executions | lower better | ms |
| ``queue_delay`` | executions whose queue wait exceeds target | executions that queued | lower better | ms |

Everything is deterministic: same rows, same window, same numbers. No model,
no scoring, no randomness.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Float, case, func, literal, select
from sqlalchemy.orm import Session

from app.models.runtime import AgentDeployment, AgentExecution, ToolCall

#: Terminal execution statuses -- identical to 3.5's ``TERMINAL_FOR_HEALTH`` and
#: 4.5's ``TERMINAL_FOR_BEHAVIOR``; a test asserts the equality rather than
#: letting a fourth copy drift.
TERMINAL_STATUSES: frozenset[str] = frozenset({
    "SUCCEEDED", "FAILED", "TIMED_OUT", "DEAD_LETTERED", "DENIED", "BLOCKED", "CANCELLED",
})

#: ``agent_executions.error_code`` stores a 5.7a.4 ``ProviderErrorClass`` value
#: on a provider failure. Named here rather than imported so a change to the
#: taxonomy is a deliberate edit to this SLI's definition.
PROVIDER_ERROR_CODES: frozenset[str] = frozenset({
    "RATE_LIMITED", "PROVIDER_UNAVAILABLE", "TIMEOUT", "CONTEXT_LENGTH_EXCEEDED",
    "CONTENT_FILTERED", "AUTHENTICATION_FAILED", "INVALID_REQUEST",
})

#: SLI name -> (direction, unit). ``higher_better`` means the objective is
#: ``observed >= target``; ``lower_better`` means ``observed <= target``.
SLI_SPECS: dict[str, tuple[str, str]] = {
    "success_rate": ("higher_better", "ratio"),
    "timeout_rate": ("lower_better", "ratio"),
    "provider_error_rate": ("lower_better", "ratio"),
    "tool_failure_rate": ("lower_better", "ratio"),
    "latency_p95": ("lower_better", "ms"),
    "queue_delay": ("lower_better", "ms"),
}

SLI_NAMES: frozenset[str] = frozenset(SLI_SPECS)


@dataclass(frozen=True)
class SLIResult:
    """One SLI over one window. A plain value -- no Session, so it can be
    serialized into an evaluation row and compared against a target."""

    sli: str
    observed_value: float | None
    #: Denominator: terminal executions, or tool calls, or queued executions.
    sample_count: int
    #: Numerator for budget math: the count of "bad" outcomes in the window
    #: (or, for the latency SLIs, the count exceeding the target).
    bad_count: int
    unit: str

    @property
    def bad_fraction(self) -> float:
        if self.sample_count <= 0:
            return 0.0
        return self.bad_count / self.sample_count


class SLIComputer:
    """Computes an SLI over a window, tenant- and scope-scoped.

    Read-only: holds a Session but never adds, flushes or commits."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    def compute(self, sli: str, *, organization_id: uuid.UUID,
                window_start: datetime, window_end: datetime,
                scope_type: str, scope_id: uuid.UUID | None,
                latency_target_ms: float | None = None) -> SLIResult:
        if sli not in SLI_NAMES:  # pragma: no cover - validated upstream
            raise ValueError(f"unknown SLI {sli!r}")
        if sli == "tool_failure_rate":
            return self._tool_failure_rate(organization_id, window_start, window_end,
                                           scope_type, scope_id)
        if sli == "queue_delay":
            return self._queue_delay(organization_id, window_start, window_end,
                                     scope_type, scope_id, latency_target_ms)
        if sli == "latency_p95":
            return self._latency_p95(organization_id, window_start, window_end,
                                     scope_type, scope_id, latency_target_ms)
        return self._execution_rate(sli, organization_id, window_start, window_end,
                                    scope_type, scope_id)

    # ------------------------------------------------------------------ #
    def _execution_scope(self, stmt, organization_id, window_start, window_end,
                         scope_type, scope_id):
        """Tenant + time + scope predicate on ``agent_executions``. The tenant
        clause leads every plan; scope narrows further, never widens."""
        stmt = stmt.where(
            AgentExecution.organization_id == organization_id,
            AgentExecution.created_at >= window_start,
            AgentExecution.created_at <= window_end,
        )
        if scope_type == "AGENT" and scope_id is not None:
            stmt = stmt.where(AgentExecution.agent_id == scope_id)
        elif scope_type == "VERSION" and scope_id is not None:
            stmt = stmt.where(AgentExecution.agent_version_id == scope_id)
        elif scope_type == "ENVIRONMENT" and scope_id is not None:
            stmt = stmt.where(
                select(AgentDeployment.id).where(
                    AgentDeployment.id == AgentExecution.deployment_id,
                    AgentDeployment.environment_id == scope_id,
                ).exists()
            )
        return stmt

    def _execution_rate(self, sli, organization_id, window_start, window_end,
                        scope_type, scope_id) -> SLIResult:
        terminal = case((AgentExecution.status.in_(tuple(TERMINAL_STATUSES)), 1), else_=0)
        if sli == "success_rate":
            bad = case((AgentExecution.status.in_(tuple(TERMINAL_STATUSES))
                        & (AgentExecution.status != "SUCCEEDED"), 1), else_=0)
        elif sli == "timeout_rate":
            bad = case((AgentExecution.status == "TIMED_OUT", 1), else_=0)
        elif sli == "provider_error_rate":
            bad = case((AgentExecution.status.in_(tuple(TERMINAL_STATUSES))
                        & AgentExecution.error_code.in_(tuple(PROVIDER_ERROR_CODES)), 1),
                       else_=0)
        else:  # pragma: no cover
            raise ValueError(sli)

        stmt = self._execution_scope(
            select(func.coalesce(func.sum(terminal), 0), func.coalesce(func.sum(bad), 0)),
            organization_id, window_start, window_end, scope_type, scope_id)
        total, bad_count = self.db.execute(stmt).one()
        total, bad_count = int(total or 0), int(bad_count or 0)

        if total == 0:
            return SLIResult(sli=sli, observed_value=None, sample_count=0,
                             bad_count=0, unit="ratio")
        if sli == "success_rate":
            observed = (total - bad_count) / total
        else:
            observed = bad_count / total
        return SLIResult(sli=sli, observed_value=observed, sample_count=total,
                         bad_count=bad_count, unit="ratio")

    def _latency_p95(self, organization_id, window_start, window_end,
                     scope_type, scope_id, target_ms) -> SLIResult:
        over = (case((AgentExecution.duration_ms > target_ms, 1), else_=0)
                if target_ms is not None else literal(0))
        stmt = self._execution_scope(
            select(
                func.count(AgentExecution.id),
                func.percentile_cont(0.95).within_group(
                    AgentExecution.duration_ms.cast(Float).asc()),
                func.coalesce(func.sum(over), 0),
            ),
            organization_id, window_start, window_end, scope_type, scope_id
        ).where(AgentExecution.status.in_(tuple(TERMINAL_STATUSES)),
                AgentExecution.duration_ms.is_not(None))
        total, p95, over_count = self.db.execute(stmt).one()
        total = int(total or 0)
        return SLIResult(
            sli="latency_p95",
            observed_value=float(p95) if p95 is not None else None,
            sample_count=total, bad_count=int(over_count or 0), unit="ms")

    def _queue_delay(self, organization_id, window_start, window_end,
                     scope_type, scope_id, target_ms) -> SLIResult:
        delay = (func.extract("epoch", AgentExecution.started_at - AgentExecution.queued_at)
                 * 1000.0)
        over = (case((delay > target_ms, 1), else_=0)
                if target_ms is not None else literal(0))
        stmt = self._execution_scope(
            select(
                func.count(AgentExecution.id),
                func.percentile_cont(0.95).within_group(delay.cast(Float).asc()),
                func.coalesce(func.sum(over), 0),
            ),
            organization_id, window_start, window_end, scope_type, scope_id
        ).where(AgentExecution.queued_at.is_not(None),
                AgentExecution.started_at.is_not(None))
        total, p95, over_count = self.db.execute(stmt).one()
        total = int(total or 0)
        return SLIResult(
            sli="queue_delay",
            observed_value=float(p95) if p95 is not None else None,
            sample_count=total, bad_count=int(over_count or 0), unit="ms")

    def _tool_failure_rate(self, organization_id, window_start, window_end,
                           scope_type, scope_id) -> SLIResult:
        """Failed tool calls / tool calls. A tool call is a failure when it
        carries an ``error_code``/``error_class`` or its status is not
        ``ALLOWED`` -- the exact 5.6a.2 predicate 4.5 also reuses.

        ``tool_calls`` has no ``organization_id`` of its own (4.5's engine
        relies on ``agent_id`` being tenant-unique); this joins
        ``agent_executions`` for the tenant predicate so an ORG-scoped SLO is
        still correctly isolated."""
        failed = case(
            ((ToolCall.error_code.is_not(None)) | (ToolCall.error_class.is_not(None))
             | (ToolCall.status != "ALLOWED"), 1), else_=0)
        stmt = (
            select(func.count(ToolCall.id), func.coalesce(func.sum(failed), 0))
            .join(AgentExecution, AgentExecution.id == ToolCall.execution_id)
            .where(
                AgentExecution.organization_id == organization_id,
                ToolCall.created_at >= window_start,
                ToolCall.created_at <= window_end,
            )
        )
        if scope_type == "AGENT" and scope_id is not None:
            stmt = stmt.where(ToolCall.agent_id == scope_id)
        elif scope_type == "VERSION" and scope_id is not None:
            stmt = stmt.where(AgentExecution.agent_version_id == scope_id)
        elif scope_type == "ENVIRONMENT" and scope_id is not None:
            stmt = stmt.where(
                select(AgentDeployment.id).where(
                    AgentDeployment.id == AgentExecution.deployment_id,
                    AgentDeployment.environment_id == scope_id,
                ).exists()
            )
        total, bad_count = self.db.execute(stmt).one()
        total, bad_count = int(total or 0), int(bad_count or 0)
        if total == 0:
            return SLIResult(sli="tool_failure_rate", observed_value=None,
                             sample_count=0, bad_count=0, unit="ratio")
        return SLIResult(sli="tool_failure_rate", observed_value=bad_count / total,
                         sample_count=total, bad_count=bad_count, unit="ratio")
