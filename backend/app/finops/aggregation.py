"""Real-cost aggregation (M4-4.4-FR-001..004).

Every figure here comes from ``agent_executions.cost_amount``. Nothing is
recomputed, nothing is estimated, and nothing is stored.

**Actual and estimated are never added together.** ``cost_is_estimated`` exists
on the execution row precisely because the platform sometimes cannot meter a
call — a provider that reported no usage, a self-hosted endpoint with no
pricing row. Summing those into a total labelled "spend" would produce a number
an operator would take to their finance team. So every aggregate returns
``actual_amount`` and ``estimated_amount`` as separate figures, and the caller
has to decide what to do with the second one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Select, and_, case, func, select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.runtime import AgentDeployment, AgentExecution, AgentVersion

# The dimensions a cost figure can be broken down by. Bounded on purpose: an
# open-ended `group_by` parameter over user-supplied column names is a SQL
# injection surface and an unbounded-cardinality surface at once. Phase 4.1's
# metric-cardinality rule applied to a different plane.
DIMENSIONS: frozenset[str] = frozenset({
    "agent", "agent_version", "environment", "provider", "model", "project",
    "department", "status",
})

# A summary never scans further back than this without an explicit range, for
# the same reason Phase 4.2's explorer has a default window: an absent time
# range must not mean "everything".
DEFAULT_WINDOW = timedelta(days=30)
MAX_GROUPS = 500


class CostDimensionError(ValueError):
    """Raised for a dimension outside :data:`DIMENSIONS`."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class CostFilters:
    """What an aggregation is scoped to. ``organization_id`` is not here — it
    is a required argument to every method, so it cannot be forgotten by
    omission the way an optional filter can."""

    agent_id: uuid.UUID | None = None
    agent_version_id: uuid.UUID | None = None
    deployment_id: uuid.UUID | None = None
    environment: str | None = None
    provider: str | None = None
    model: str | None = None
    project_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    started_after: datetime | None = None
    started_before: datetime | None = None


@dataclass(frozen=True)
class CostBucket:
    """One row of a breakdown or one point on a time series."""

    key: str
    label: str | None
    actual_amount: float
    estimated_amount: float
    execution_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    currency: str = "USD"

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "actual_amount": round(self.actual_amount, 8),
            "estimated_amount": round(self.estimated_amount, 8),
            "execution_count": self.execution_count,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "currency": self.currency,
        }


@dataclass(frozen=True)
class CostSummary:
    window_start: datetime
    window_end: datetime
    actual_amount: float
    estimated_amount: float
    execution_count: int
    total_tokens: int
    unpriced_execution_count: int
    dimension: str | None = None
    buckets: tuple[CostBucket, ...] = field(default_factory=tuple)
    currency: str = "USD"

    def as_dict(self) -> dict[str, Any]:
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "actual_amount": round(self.actual_amount, 8),
            "estimated_amount": round(self.estimated_amount, 8),
            "execution_count": self.execution_count,
            "total_tokens": self.total_tokens,
            "unpriced_execution_count": self.unpriced_execution_count,
            "currency": self.currency,
            "dimension": self.dimension,
            "buckets": [b.as_dict() for b in self.buckets],
        }


@dataclass(frozen=True)
class SpendAnomaly:
    """M4-4.4-FR-003 — a spend spike, stated so an operator can check the
    arithmetic themselves. Deterministic by construction: no model, no training
    data, no threshold learned from anything. Behavioural signal detection is
    Phase 4.5's, and it is a different kind of claim."""

    period: str
    amount: float
    baseline: float
    ratio: float
    threshold_ratio: float
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "amount": round(self.amount, 8),
            "baseline": round(self.baseline, 8),
            "ratio": round(self.ratio, 4),
            "threshold_ratio": self.threshold_ratio,
            "reason": self.reason,
        }


class CostAggregator:
    """The canonical financial read model over real runtime cost (Gate D).

    Every statement built here leads with ``organization_id`` and a time range,
    in that order, so the plan starts from ``ix_agent_executions_org_created``
    (Phase 4.2's index) rather than from a filter that could match across
    tenants. That is both the isolation property and the performance one, which
    is not a coincidence: a query that cannot scan another tenant's rows also
    cannot scan the whole table.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Statement construction
    # ------------------------------------------------------------------ #
    def _base(self, organization_id: uuid.UUID, filters: CostFilters) -> tuple[Select, datetime, datetime]:
        window_end = filters.started_before or _now()
        window_start = filters.started_after or (window_end - DEFAULT_WINDOW)

        stmt = select(AgentExecution).where(
            AgentExecution.organization_id == organization_id,
            AgentExecution.created_at >= window_start,
            AgentExecution.created_at <= window_end,
        )
        if filters.agent_id:
            stmt = stmt.where(AgentExecution.agent_id == filters.agent_id)
        if filters.agent_version_id:
            stmt = stmt.where(AgentExecution.agent_version_id == filters.agent_version_id)
        if filters.deployment_id:
            stmt = stmt.where(AgentExecution.deployment_id == filters.deployment_id)
        if filters.environment:
            # A correlated EXISTS rather than a join, for the reason Phase 4.2
            # documented: a join multiplies rows and then needs a DISTINCT,
            # which reintroduces the sort the recency index exists to remove.
            stmt = stmt.where(
                select(AgentDeployment.id).where(
                    AgentDeployment.id == AgentExecution.deployment_id,
                    AgentDeployment.environment == filters.environment,
                ).exists()
            )
        if filters.provider or filters.model:
            conditions = [AgentVersion.id == AgentExecution.agent_version_id]
            if filters.provider:
                conditions.append(
                    AgentVersion.model_configuration["provider"].astext == filters.provider)
            if filters.model:
                conditions.append(
                    AgentVersion.model_configuration["model"].astext == filters.model)
            stmt = stmt.where(select(AgentVersion.id).where(and_(*conditions)).exists())
        if filters.project_id or filters.department_id:
            conditions = [Agent.id == AgentExecution.agent_id]
            if filters.project_id:
                conditions.append(Agent.project_id == filters.project_id)
            if filters.department_id:
                conditions.append(Agent.department_id == filters.department_id)
            stmt = stmt.where(select(Agent.id).where(and_(*conditions)).exists())
        return stmt, window_start, window_end

    # The two sums, kept apart. `cost_is_estimated` splits them; a NULL
    # `cost_amount` (a call the platform could not meter at all) counts in
    # neither and is reported separately as `unpriced_execution_count`, because
    # silently treating "we don't know" as zero is how a spend figure becomes a
    # lie an operator repeats to their finance team.
    _ACTUAL = func.coalesce(func.sum(case(
        (and_(AgentExecution.cost_amount.is_not(None),
              AgentExecution.cost_is_estimated.is_(False)), AgentExecution.cost_amount),
        else_=0)), 0)
    _ESTIMATED = func.coalesce(func.sum(case(
        (and_(AgentExecution.cost_amount.is_not(None),
              AgentExecution.cost_is_estimated.is_(True)), AgentExecution.cost_amount),
        else_=0)), 0)
    _UNPRICED = func.coalesce(func.sum(case(
        (AgentExecution.cost_amount.is_(None), 1), else_=0)), 0)

    def _totals(self, base: Select):
        return base.with_only_columns(
            self._ACTUAL.label("actual"),
            self._ESTIMATED.label("estimated"),
            func.count(AgentExecution.id).label("executions"),
            func.coalesce(func.sum(AgentExecution.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(AgentExecution.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(AgentExecution.total_tokens), 0).label("total_tokens"),
            self._UNPRICED.label("unpriced"),
        ).order_by(None)

    # ------------------------------------------------------------------ #
    # Public read model
    # ------------------------------------------------------------------ #
    def summary(self, organization_id: uuid.UUID, *, filters: CostFilters | None = None,
                dimension: str | None = None) -> CostSummary:
        """M4-4.4-FR-001 — the total, optionally broken down by one dimension."""
        filters = filters or CostFilters()
        if dimension is not None and dimension not in DIMENSIONS:
            raise CostDimensionError(
                f"Unknown cost dimension '{dimension}'. Known: {sorted(DIMENSIONS)}.")

        base, window_start, window_end = self._base(organization_id, filters)
        row = self.db.execute(self._totals(base)).one()
        buckets = self._breakdown(base, dimension) if dimension else ()

        return CostSummary(
            window_start=window_start, window_end=window_end,
            actual_amount=float(row.actual), estimated_amount=float(row.estimated),
            execution_count=int(row.executions), total_tokens=int(row.total_tokens),
            unpriced_execution_count=int(row.unpriced),
            dimension=dimension, buckets=buckets,
        )

    def _breakdown(self, base: Select, dimension: str) -> tuple[CostBucket, ...]:
        """One breakdown, by one bounded dimension.

        The three that are not columns on ``agent_executions`` reach their
        value through a join here rather than an ``EXISTS``, because a grouping
        key has to be *selected*, not merely tested for. The join is on a
        primary key in every case and the tenant predicate has already narrowed
        the driving side, so this stays an index nested loop."""
        stmt = base
        if dimension == "agent":
            key, label = AgentExecution.agent_id, Agent.name
            stmt = stmt.join(Agent, Agent.id == AgentExecution.agent_id)
        elif dimension == "agent_version":
            key, label = AgentExecution.agent_version_id, AgentVersion.version
            stmt = stmt.join(AgentVersion, AgentVersion.id == AgentExecution.agent_version_id)
        elif dimension == "environment":
            stmt = stmt.join(AgentDeployment,
                             AgentDeployment.id == AgentExecution.deployment_id)
            key, label = AgentDeployment.environment, AgentDeployment.environment
        elif dimension in ("provider", "model"):
            stmt = stmt.join(AgentVersion, AgentVersion.id == AgentExecution.agent_version_id)
            key = AgentVersion.model_configuration[dimension].astext
            label = key
        elif dimension in ("project", "department"):
            stmt = stmt.join(Agent, Agent.id == AgentExecution.agent_id)
            key = Agent.project_id if dimension == "project" else Agent.department_id
            label = key
        else:  # status
            key, label = AgentExecution.status, AgentExecution.status

        rows = self.db.execute(
            stmt.with_only_columns(
                key.label("key"), label.label("label"),
                self._ACTUAL.label("actual"), self._ESTIMATED.label("estimated"),
                func.count(AgentExecution.id).label("executions"),
                func.coalesce(func.sum(AgentExecution.prompt_tokens), 0).label("prompt_tokens"),
                func.coalesce(func.sum(AgentExecution.completion_tokens), 0).label("completion_tokens"),
                func.coalesce(func.sum(AgentExecution.total_tokens), 0).label("total_tokens"),
            ).order_by(None).group_by(key, label)
            .order_by(self._ACTUAL.desc()).limit(MAX_GROUPS)
        ).all()

        return tuple(
            CostBucket(
                key="" if r.key is None else str(r.key),
                label=None if r.label is None else str(r.label),
                actual_amount=float(r.actual), estimated_amount=float(r.estimated),
                execution_count=int(r.executions), prompt_tokens=int(r.prompt_tokens),
                completion_tokens=int(r.completion_tokens), total_tokens=int(r.total_tokens),
            )
            for r in rows
        )

    def timeseries(self, organization_id: uuid.UUID, *, filters: CostFilters | None = None,
                   granularity: str = "day") -> tuple[CostBucket, ...]:
        """M4-4.4-FR-003 — spend over time, bucketed in the database.

        ``date_trunc`` rather than fetching rows and bucketing in Python: at
        90,000 executions the second approach transfers the whole window to the
        application to produce thirty numbers."""
        if granularity not in ("hour", "day", "month"):
            raise CostDimensionError(
                f"Unknown granularity '{granularity}'. Known: hour, day, month.")
        filters = filters or CostFilters()
        base, _start, _end = self._base(organization_id, filters)
        bucket = func.date_trunc(granularity, AgentExecution.created_at)

        rows = self.db.execute(
            base.with_only_columns(
                bucket.label("bucket"),
                self._ACTUAL.label("actual"), self._ESTIMATED.label("estimated"),
                func.count(AgentExecution.id).label("executions"),
                func.coalesce(func.sum(AgentExecution.prompt_tokens), 0).label("prompt_tokens"),
                func.coalesce(func.sum(AgentExecution.completion_tokens), 0).label("completion_tokens"),
                func.coalesce(func.sum(AgentExecution.total_tokens), 0).label("total_tokens"),
            ).order_by(None).group_by(bucket).order_by(bucket)
        ).all()

        return tuple(
            CostBucket(
                key=r.bucket.isoformat(), label=None,
                actual_amount=float(r.actual), estimated_amount=float(r.estimated),
                execution_count=int(r.executions), prompt_tokens=int(r.prompt_tokens),
                completion_tokens=int(r.completion_tokens), total_tokens=int(r.total_tokens),
            )
            for r in rows
        )

    def anomalies(self, organization_id: uuid.UUID, *, filters: CostFilters | None = None,
                  granularity: str = "day", threshold_ratio: float = 3.0,
                  min_baseline: float = 0.0) -> tuple[SpendAnomaly, ...]:
        """M4-4.4-FR-003 — deterministic spend-spike surfacing.

        The rule, in full, because a cost alert nobody can reproduce by hand is
        a cost alert nobody trusts: **a period is anomalous when its actual
        spend exceeds ``threshold_ratio`` times the mean of the periods before
        it.** The baseline is the trailing mean, recomputed at each period, and
        every number that produced the verdict is returned alongside it.

        ``min_baseline`` exists because ratios are meaningless against almost
        nothing: $0.02 following a $0.001 day is a 20× "spike" and is noise.
        The same reasoning gave Phase 3.5's canary health an
        ``INSUFFICIENT_DATA`` floor — a thin sample is not evidence.

        No model, no training, no learned threshold. Behavioural anomaly
        detection is Phase 4.5's, and it is a different kind of claim."""
        series = self.timeseries(organization_id, filters=filters, granularity=granularity)
        out: list[SpendAnomaly] = []
        for index, point in enumerate(series):
            if index == 0:
                continue
            prior = [p.actual_amount for p in series[:index]]
            baseline = sum(prior) / len(prior)
            if baseline <= min_baseline or baseline <= 0:
                continue
            ratio = point.actual_amount / baseline
            if ratio >= threshold_ratio:
                out.append(SpendAnomaly(
                    period=point.key, amount=point.actual_amount, baseline=baseline,
                    ratio=ratio, threshold_ratio=threshold_ratio,
                    reason=(f"Spend of {point.actual_amount:.6f} is {ratio:.1f}x the trailing "
                            f"mean of {baseline:.6f} over the previous {len(prior)} "
                            f"{granularity}(s)."),
                ))
        return tuple(out)

    def provenance(self, organization_id: uuid.UUID, execution_id: uuid.UUID) -> dict[str, Any] | None:
        """M4-4.4-FR-004 / §10 — how one charge was arrived at.

        Every field returned here was written at execution time and is never
        updated afterwards. ``PricingService.set_price`` closes the previous
        price row and inserts a new one rather than mutating in place, so the
        ``pricing_version`` recorded on the execution still names the exact
        price document that produced its ``cost_amount``. A price change today
        cannot alter what a charge from last month says it was — which is the
        whole of §10, and it is a property of how pricing was already built
        rather than something this phase adds."""
        row = self.db.execute(
            select(AgentExecution).where(
                AgentExecution.organization_id == organization_id,
                AgentExecution.id == execution_id,
            )
        ).scalars().first()
        if row is None:
            return None
        version = self.db.get(AgentVersion, row.agent_version_id)
        configuration = (version.model_configuration or {}) if version else {}
        return {
            "execution_id": str(row.id),
            "provider": configuration.get("provider"),
            "model": configuration.get("model"),
            "pricing_version": row.pricing_version,
            "prompt_tokens": row.prompt_tokens,
            "completion_tokens": row.completion_tokens,
            "total_tokens": row.total_tokens,
            "token_accounting_complete": row.token_accounting_complete,
            "calculated_amount": None if row.cost_amount is None else float(row.cost_amount),
            "currency": row.cost_currency,
            "is_estimated": row.cost_is_estimated,
            "calculated_at": row.completed_at or row.created_at,
        }
