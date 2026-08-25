"""Phase 4.2 -- the trace explorer: finding the execution you need
(ACT-SRS-M4 §6, §15, §26, §28).

Trace *detail* (:mod:`app.observability.assembly`) answers "what happened in
this execution?". This module answers the question that comes first and is
usually harder: **which execution?**

**Every query here is tenant-scoped by construction.** There is no code path in
this module that builds a statement without an `organization_id` predicate --
not an internal helper, not an admin variant, not a "count all" for a total.
That is deliberate: §34 forbids not only reading another tenant's data but
inferring its existence, and a total row count is an inference. Counts here are
counts *within the tenant*, and the tenant is the first thing every statement
filters on.

**The index this relies on, and why it exists.** Phase 4.2's measurement found
that `agent_executions` had no index on `created_at` at all, so the default
listing planned as a bitmap scan over every row a tenant owns followed by a
top-N sort -- O(tenant size). Migration 0046 added
`(organization_id, created_at DESC)`, which turns it into an index scan that
stops at the LIMIT -- O(limit), flat as a tenant grows. The column order and the
`DESC` both matter: the leading column must be the tenant because every query
filters on it first, and the direction must match the `ORDER BY` or the sort
comes back.

**Metadata only.** A result row carries identities, timings, status, cost and
token counts. It carries no prompt, no tool argument, no model output. That is
4.8's territory, behind capture policy and a stronger permission.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Select, and_, exists, select
from sqlalchemy.orm import Session

from app.models.runtime import (
    AgentDeployment,
    AgentExecution,
    AgentVersion,
    ToolCall,
)
from app.observability.trace import trace_id_for

#: Hard ceiling on a page. A caller asking for more gets this many. Bounded
#: rather than validated-and-rejected because a large `limit` is a clumsy
#: request, not an attack, and failing it would be less useful than serving it
#: safely (SRS §26).
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50

#: The default time window when a caller supplies none. An unbounded explorer
#: query is the one shape that stays cheap on a small tenant and becomes a
#: table scan on a large one, so the API refuses to have an unbounded default
#: -- a caller who genuinely wants everything must ask for a wider window and
#: say so.
DEFAULT_WINDOW = timedelta(days=30)

#: Statuses an execution may hold. Used to reject an unknown filter value
#: early, so a typo returns an empty page rather than silently matching nothing
#: after a full query.
_KNOWN_STATUSES = frozenset({
    "CREATED", "AUTHORIZING", "DENIED", "PENDING_APPROVAL", "REJECTED", "QUEUED",
    "SCHEDULED", "RUNNING", "WAITING_FOR_TOOL", "WAITING_FOR_APPROVAL", "RETRYING",
    "SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED", "BLOCKED", "SUSPENDED",
    "DEAD_LETTERED",
})


@dataclass(frozen=True)
class TraceFilters:
    """The explorer's filter set (M4-4.2-FR-010).

    Frozen, and every field optional. A filter that is `None` is absent from
    the query entirely rather than compiled as a no-op predicate -- an
    `IS NOT NULL`-style catch-all would defeat the index the leading columns
    were chosen for."""

    trace_id: str | None = None
    execution_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    agent_version_id: uuid.UUID | None = None
    deployment_id: uuid.UUID | None = None
    environment: str | None = None
    model: str | None = None
    provider: str | None = None
    tool_id: uuid.UUID | None = None
    status: str | None = None
    error_code: str | None = None
    #: Only executions that failed in some way. Distinct from `status` because
    #: "show me the problems" spans several terminal states.
    only_errors: bool = False
    started_after: datetime | None = None
    started_before: datetime | None = None
    #: Requires the caller to hold the actor-filter permission; the route
    #: enforces that, and this module never widens it.
    triggered_by_identity_id: uuid.UUID | None = None


@dataclass
class TraceSummary:
    """One row in the explorer -- metadata only (M4-4.2-FR-012)."""

    trace_id: str
    execution_id: str
    correlated: bool
    status: str
    agent_id: str
    agent_version_id: str
    deployment_id: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    queue_wait_ms: int | None
    error_code: str | None
    cost_amount: str | None
    cost_currency: str | None
    total_tokens: int | None
    loop_iterations: int
    attempt_count: int
    termination_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "execution_id": self.execution_id,
            "correlated": self.correlated,
            "status": self.status,
            "agent_id": self.agent_id,
            "agent_version_id": self.agent_version_id,
            "deployment_id": self.deployment_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
            "queue_wait_ms": self.queue_wait_ms,
            "error_code": self.error_code,
            "cost_amount": self.cost_amount,
            "cost_currency": self.cost_currency,
            "total_tokens": self.total_tokens,
            "loop_iterations": self.loop_iterations,
            "attempt_count": self.attempt_count,
            "termination_reason": self.termination_reason,
        }


@dataclass
class TracePage:
    """A bounded page of results, plus the window it was taken over."""

    items: list[TraceSummary]
    limit: int
    offset: int
    #: True when more rows exist past this page. Derived by fetching one extra
    #: row rather than issuing a `COUNT(*)`: a count over a large tenant costs
    #: a full index traversal to produce a number the UI shows as "1,000+"
    #: anyway.
    has_more: bool
    window_start: datetime | None
    window_end: datetime | None
    filters_applied: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "items": [item.as_dict() for item in self.items],
            "limit": self.limit,
            "offset": self.offset,
            "has_more": self.has_more,
            "window_start": self.window_start.isoformat() if self.window_start else None,
            "window_end": self.window_end.isoformat() if self.window_end else None,
            "filters_applied": self.filters_applied,
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _gap_ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds() * 1000))


class TraceExplorer:
    """Searches executions within one tenant. Read-only by construction."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    def search(self, organization_id: uuid.UUID, filters: TraceFilters | None = None,
               *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0) -> TracePage:
        filters = filters or TraceFilters()
        limit = max(1, min(int(limit), MAX_PAGE_SIZE))
        offset = max(0, int(offset))

        window_end = filters.started_before or _now()
        window_start = filters.started_after or (window_end - DEFAULT_WINDOW)

        stmt, applied = self._build(organization_id, filters, window_start, window_end)

        # One extra row decides `has_more` without a COUNT.
        stmt = stmt.order_by(AgentExecution.created_at.desc()).limit(limit + 1).offset(offset)
        rows = list(self.db.execute(stmt).scalars())
        has_more = len(rows) > limit
        rows = rows[:limit]

        return TracePage(
            items=[self._summarize(row) for row in rows],
            limit=limit, offset=offset, has_more=has_more,
            window_start=window_start, window_end=window_end,
            filters_applied=applied,
        )

    def find_by_trace_id(self, organization_id: uuid.UUID,
                         trace_id: str) -> list[AgentExecution]:
        """Executions belonging to one trace.

        A trace id is either a caller-supplied `correlation_id` -- which may
        legitimately span several executions -- or an execution's own primary
        key, used as the derived fallback when no correlation was supplied
        (4.1's `trace_id_for`). Both are resolved here, correlation first,
        because a correlation match is the caller's own intent and an id match
        is our inference.

        The tenant predicate is applied to *both* lookups. Resolving the id
        branch without it would let one tenant confirm another's execution id
        exists by observing the difference between a 404 and an empty list --
        the enumeration §34 forbids."""
        by_correlation = list(self.db.execute(
            select(AgentExecution)
            .where(AgentExecution.organization_id == organization_id,
                   AgentExecution.correlation_id == trace_id)
            .order_by(AgentExecution.created_at)
        ).scalars())
        if by_correlation:
            return by_correlation

        try:
            candidate = uuid.UUID(str(trace_id))
        except (ValueError, AttributeError, TypeError):
            return []
        execution = self.db.execute(
            select(AgentExecution).where(
                AgentExecution.id == candidate,
                AgentExecution.organization_id == organization_id,
            )
        ).scalar_one_or_none()
        # Only a *derived* trace id resolves this way. An execution that has a
        # correlation of its own belongs to that trace, and answering to its
        # primary key as well would give one execution two trace identities.
        if execution is not None and execution.correlation_id is None:
            return [execution]
        return []

    # ------------------------------------------------------------------ #
    def _build(self, organization_id: uuid.UUID, filters: TraceFilters,
               window_start: datetime, window_end: datetime) -> tuple[Select, list[str]]:
        """Compile the filter set into one statement.

        The tenant predicate and the time window are applied first and always,
        so the `(organization_id, created_at DESC)` index leads on every plan.
        Everything else narrows what that index scan already returned."""
        applied: list[str] = []
        conditions = [
            AgentExecution.organization_id == organization_id,
            AgentExecution.created_at >= window_start,
            AgentExecution.created_at <= window_end,
        ]

        def add(condition, name: str) -> None:
            conditions.append(condition)
            applied.append(name)

        if filters.execution_id is not None:
            add(AgentExecution.id == filters.execution_id, "execution_id")
        if filters.trace_id:
            add(AgentExecution.correlation_id == filters.trace_id, "trace_id")
        if filters.agent_id is not None:
            add(AgentExecution.agent_id == filters.agent_id, "agent_id")
        if filters.agent_version_id is not None:
            add(AgentExecution.agent_version_id == filters.agent_version_id, "agent_version_id")
        if filters.deployment_id is not None:
            add(AgentExecution.deployment_id == filters.deployment_id, "deployment_id")
        if filters.status:
            add(AgentExecution.status == filters.status.upper(), "status")
        if filters.error_code:
            add(AgentExecution.error_code == filters.error_code, "error_code")
        if filters.only_errors:
            add(AgentExecution.error_code.isnot(None), "only_errors")
        if filters.triggered_by_identity_id is not None:
            add(AgentExecution.triggered_by_identity_id == filters.triggered_by_identity_id,
                "triggered_by")

        # --- dimensions that are not columns on agent_executions -----------
        # Each is a correlated EXISTS rather than a JOIN. A join would multiply
        # rows when the child side is not unique (a tool filter would return one
        # execution row per matching tool call) and then need a DISTINCT, which
        # reintroduces the sort the 0046 index exists to remove.
        if filters.environment:
            add(exists().where(and_(
                AgentDeployment.id == AgentExecution.deployment_id,
                AgentDeployment.environment == filters.environment.upper(),
            )), "environment")

        if filters.model or filters.provider:
            version_conditions = [AgentVersion.id == AgentExecution.agent_version_id]
            if filters.model:
                version_conditions.append(
                    AgentVersion.model_configuration["model"].astext == filters.model)
                applied.append("model")
            if filters.provider:
                version_conditions.append(
                    AgentVersion.model_configuration["provider"].astext
                    == filters.provider.upper())
                applied.append("provider")
            conditions.append(exists().where(and_(*version_conditions)))

        if filters.tool_id is not None:
            add(exists().where(and_(
                ToolCall.execution_id == AgentExecution.id,
                ToolCall.tool_id == filters.tool_id,
            )), "tool_id")

        return select(AgentExecution).where(and_(*conditions)), applied

    @staticmethod
    def _summarize(execution: AgentExecution) -> TraceSummary:
        return TraceSummary(
            trace_id=trace_id_for(execution),
            execution_id=str(execution.id),
            correlated=execution.correlation_id is not None,
            status=execution.status,
            agent_id=str(execution.agent_id),
            agent_version_id=str(execution.agent_version_id),
            deployment_id=str(execution.deployment_id) if execution.deployment_id else None,
            created_at=execution.created_at,
            started_at=execution.started_at,
            completed_at=execution.completed_at,
            duration_ms=execution.duration_ms,
            queue_wait_ms=_gap_ms(execution.queued_at, execution.started_at),
            error_code=execution.error_code,
            cost_amount=str(execution.cost_amount) if execution.cost_amount is not None else None,
            cost_currency=execution.cost_currency,
            total_tokens=execution.total_tokens,
            loop_iterations=execution.loop_iterations,
            attempt_count=execution.attempt_count,
            termination_reason=execution.termination_reason,
        )


def is_known_status(value: str | None) -> bool:
    return value is None or value.upper() in _KNOWN_STATUSES
