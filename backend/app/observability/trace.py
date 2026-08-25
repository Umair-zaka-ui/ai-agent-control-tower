"""Phase 4.1 -- trace and span context (ACT-SRS-M4 §6, §13).

**One execution is one trace.** The trace identity is the execution's
``correlation_id`` -- a column that has existed on ``agent_executions`` since
Milestone 1 and has been almost entirely unused (see ``docs/observability/
architecture.md`` for the measurement). 4.1 does not introduce a new identity;
it makes the existing one actually get populated, and gives every execution --
including the ones already in the database with a null column -- a stable trace
identity through :func:`trace_id_for`.

**Spans are derived, not stored.** This is the §13 decision and it is the most
consequential one in the phase. The obvious design is a ``runtime_trace_spans``
table with a row per model call and tool call. That table would be a second,
lossy copy of ``execution_attempts``, ``execution_messages`` and ``tool_calls``
-- rows that already exist, already carry timings, already carry outcomes, and
are already the authoritative record. Two copies of one fact is two things to
keep in step, and the copy is the one that goes stale.

So a span id here is a *pure function* of the trace id, the span kind and the
identity of the domain row the span describes. Same inputs, same id, forever,
with nothing persisted. A span is assembled by walking foreign keys from the
execution (see :mod:`app.observability.assembly`), and the parent linkage comes
from the domain structure that already encodes it: a tool call belongs to an
execution, an assistant turn belongs to an iteration.

The cost of this choice is honest and worth stating: a span cannot carry an
attribute that is not derivable from a domain row. If a later phase needs one,
it adds a column to the row that owns the fact -- which is where the fact
belonged anyway.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from app.observability.attributes import SemanticAttributes

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.runtime import AgentExecution

#: The namespace every derived span id is generated under. A fixed UUID5
#: namespace makes span ids deterministic *and* collision-free across trace
#: ids, without needing a registry or a sequence.
SPAN_NAMESPACE = uuid.UUID("6ba7b814-9dad-11d1-80b4-00c04fd430c8")

#: The header a caller uses to join an execution to a trace it already owns.
#: Matches the spelling the rest of this codebase already reads in
#: ``app/api/deps.py`` and the identity/authorization routes, rather than
#: introducing a fourth convention.
CORRELATION_HEADER = "x-correlation-id"
REQUEST_HEADER = "x-request-id"

#: Trace and request ids are stored in ``String(100)`` columns. A caller-
#: supplied header is untrusted input, so it is bounded here rather than at the
#: database, where over-length would be an error instead of a truncation.
MAX_ID_LENGTH = 100


class SpanKind(str, Enum):
    """The span boundaries that map to this platform's execution structure
    (M4-4.1-FR-004).

    Each kind corresponds to something that already exists as a row or an
    identifiable phase, which is what makes derivation possible at all."""

    #: The whole execution, root of the trace. Backed by ``agent_executions``.
    EXECUTION = "execution"
    #: The authorization/policy gate before an execution is queued. Phase-
    #: backed rather than row-backed: it has no table of its own, but it has a
    #: definite start and end within the request.
    AUTHORIZATION = "authorization"
    #: Phase 4.2 -- the runtime policy evaluation (§38, §46-§48) that can BLOCK
    #: an execution after authorization allows it. Distinct from AUTHORIZATION
    #: because they answer different questions and fail with different codes:
    #: "may this principal?" versus "does this request violate a runtime rule?".
    RUNTIME_POLICY = "runtime_policy"
    #: Phase 4.2 -- time spent QUEUED before a worker claimed the execution.
    #: A **computed gap**, not a row: nothing records "the queue" as an entity,
    #: but `queued_at`->`started_at` is a real, externally-meaningful interval
    #: and often the largest one in a slow trace.
    QUEUE = "queue"
    #: Phase 4.2 -- a human approval or challenge. Backed by `runtime_approvals`.
    APPROVAL = "approval"
    #: One worker's attempt, from claim to terminal state. Backed by
    #: ``execution_attempts``.
    ATTEMPT = "attempt"
    #: One model call within an attempt. Backed by the assistant row in
    #: ``execution_messages`` for that loop iteration.
    MODEL_CALL = "model_call"
    #: One tool invocation. Backed by ``tool_calls``.
    TOOL_CALL = "tool_call"
    #: An outbound call to an external system (a connector, an HTTP egress).
    #: Backed by the HTTP columns on ``tool_calls`` where present.
    EXTERNAL_CALL = "external_call"
    #: Terminal accounting -- status, cost, token totals.
    FINALIZATION = "finalization"
    #: A scheduler-driven occurrence (M4-4.1-FR-003). Backed by ``job_runs``.
    SCHEDULED_JOB = "scheduled_job"


def _bounded(value: Any) -> str | None:
    """Normalize an untrusted id to a bounded, non-empty string, or ``None``."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:MAX_ID_LENGTH]


def new_trace_id() -> str:
    """Mint a trace id for a request that arrived without one."""
    return str(uuid.uuid4())


def trace_id_for(execution: "AgentExecution") -> str:
    """The stable trace identity of an execution.

    ``correlation_id`` when it is set, and the execution's own primary key
    otherwise. That fallback is why 4.1 needs no data backfill: the ~74,000
    executions already in this database with a null ``correlation_id`` get a
    stable, unique trace identity the moment this function is called, without
    a migration writing 74,000 rows it could never reverse.

    It also means the fallback is not a degraded mode. An execution that was
    never part of a wider caller-defined trace genuinely *is* its own trace,
    and its primary key is the correct name for that trace."""
    return execution.correlation_id or str(execution.id)


def derive_span_id(trace_id: str, kind: SpanKind, row_id: Any = None,
                   ordinal: int | None = None) -> str:
    """The deterministic id of one span (M4-4.1-FR-001).

    A UUID5 over ``trace/kind/row/ordinal``. Deterministic, so recomputing a
    trace tomorrow produces byte-identical span ids and a stored reference to
    one (``runtime_events.span_id``) stays valid without the span itself ever
    having been written down.

    ``ordinal`` disambiguates spans of one kind against one row -- a model call
    per loop iteration against a single execution, for instance."""
    parts = [str(trace_id), kind.value, str(row_id) if row_id is not None else "-",
             str(ordinal) if ordinal is not None else "-"]
    return str(uuid.uuid5(SPAN_NAMESPACE, "|".join(parts)))


@dataclass(frozen=True)
class SpanContext:
    """One span: an identity, a parent, a kind, and the row it describes.

    Carries no timings or outcome of its own. Those live on the domain row and
    are read from it at assembly time -- a span that cached them would be the
    duplicate-of-the-database §13 forbids, one field at a time."""

    trace_id: str
    span_id: str
    kind: SpanKind
    parent_span_id: str | None = None
    #: The primary key of the domain row this span describes, when it has one.
    #: ``AUTHORIZATION`` and ``FINALIZATION`` are phases rather than rows and
    #: leave this null.
    row_id: str | None = None
    attributes: SemanticAttributes = field(default_factory=SemanticAttributes)

    def child(self, kind: SpanKind, row_id: Any = None, ordinal: int | None = None,
              attributes: SemanticAttributes | None = None) -> "SpanContext":
        """A child span of this one, inheriting the trace and this span as parent."""
        return SpanContext(
            trace_id=self.trace_id,
            span_id=derive_span_id(self.trace_id, kind, row_id, ordinal),
            kind=kind,
            parent_span_id=self.span_id,
            row_id=str(row_id) if row_id is not None else None,
            attributes=attributes or self.attributes,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "kind": self.kind.value,
            "row_id": self.row_id,
            "attributes": self.attributes.as_dict(),
        }


@dataclass(frozen=True)
class TraceContext:
    """The context that travels the whole execution path (M4-4.1-FR-002).

    HTTP request -> execution row -> queue -> worker -> model -> tool. It is
    plain immutable data with no database handle and no I/O, which is what lets
    it be passed across a process boundary: the worker does not receive this
    object, it *reconstructs* it from the execution row it claimed. Propagation
    across the queue therefore costs nothing and cannot fail (§9, §25) -- there
    is no serialization step to get wrong and no round-trip on the hot path."""

    trace_id: str
    request_id: str | None = None
    attributes: SemanticAttributes = field(default_factory=SemanticAttributes)

    @classmethod
    def from_headers(cls, headers: Any) -> "TraceContext":
        """Build a context from inbound HTTP headers -- the first leg.

        A caller that already threads ``x-correlation-id`` through its own
        systems has its trace joined to ours. A caller that does not gets a
        fresh trace id rather than a null: an execution with no trace identity
        is an execution that cannot be found later, which is the gap this phase
        exists to close."""
        get = getattr(headers, "get", None)
        raw_correlation = _bounded(get(CORRELATION_HEADER)) if get else None
        raw_request = _bounded(get(REQUEST_HEADER)) if get else None
        return cls(
            trace_id=raw_correlation or new_trace_id(),
            request_id=raw_request,
        )

    @classmethod
    def for_execution(cls, execution: "AgentExecution") -> "TraceContext":
        """Reconstruct the context of an execution from its row.

        This is the worker leg. A worker that claims an execution calls this
        and has the same trace identity the HTTP request created, with no
        message payload, no header propagation and no shared memory -- because
        the trace id was written to the row the worker just read."""
        return cls(
            trace_id=trace_id_for(execution),
            request_id=execution.request_id,
            attributes=SemanticAttributes.build(
                organization_id=execution.organization_id,
                agent_id=execution.agent_id,
                agent_version_id=execution.agent_version_id,
                deployment_id=execution.deployment_id,
                execution_id=execution.id,
                status=execution.status,
            ),
        )

    @classmethod
    def for_job_run(cls, job_run: Any) -> "TraceContext":
        """The scheduler leg (M4-4.1-FR-003).

        A scheduled occurrence has no caller and therefore no inbound
        correlation header, so its trace identity is its own ``job_runs`` row
        id. Derived, not stored -- for the same reason executions need no
        backfill, and so the scheduler needs no schema change at all."""
        return cls(trace_id=str(job_run.id))

    def root_span(self, kind: SpanKind = SpanKind.EXECUTION,
                  row_id: Any = None) -> SpanContext:
        """The root span of this trace."""
        return SpanContext(
            trace_id=self.trace_id,
            span_id=derive_span_id(self.trace_id, kind, row_id),
            kind=kind,
            parent_span_id=None,
            row_id=str(row_id) if row_id is not None else None,
            attributes=self.attributes,
        )

    def with_attributes(self, **values: Any) -> "TraceContext":
        """A copy with additional semantic attributes merged in."""
        merged = {**self.attributes.as_dict(), **values}
        return TraceContext(
            trace_id=self.trace_id,
            request_id=self.request_id,
            attributes=SemanticAttributes.build(**merged),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "attributes": self.attributes.as_dict(),
        }
