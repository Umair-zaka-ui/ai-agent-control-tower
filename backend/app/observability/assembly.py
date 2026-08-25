"""Phase 4.1 -- assembling a trace from the rows that already exist
(ACT-SRS-M4 §13).

This is the module that makes "spans are derived, not stored" a real claim
rather than an intention. It reads ``agent_executions`` and its children and
returns a span tree. Nothing here writes, and there is no span storage behind
it -- run it twice and you get byte-identical span ids, because
:func:`~app.observability.trace.derive_span_id` is a pure function of the trace
id, the span kind and the row's primary key.

**The span tree mirrors the domain structure, because the domain structure is
already the trace.** An execution owns attempts; an attempt runs a model loop
whose turns are ``execution_messages``; a turn requests tools whose invocations
are ``tool_calls``. That hierarchy was built for execution, not for
observability, and it happens to be exactly the parent linkage a trace needs.
Recognizing that is what let this phase add two columns instead of two tables.

**One honest limitation, stated rather than papered over.** A ``tool_calls``
row records ``loop_iteration`` but not which *attempt* it belonged to, so on a
retried execution a tool call cannot be attributed to a specific attempt from
the data alone. Rather than guess, tool spans on a multi-attempt execution
attach to the execution root, and :attr:`AssembledTrace.notes` says so. The
alternative -- attaching them to the latest attempt -- would be right most of
the time and silently wrong exactly when someone is debugging a retry, which is
the only time anyone reads a trace this closely.

Tenant scoping is the caller's job and it is not optional: every entry point
here takes an organization id and filters on it (§12, and this platform's
standing rule that a read model never sees across tenants).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.runtime import (
    AgentExecution,
    ExecutionAttempt,
    ExecutionMessage,
    RuntimeApproval,
    ToolCall,
)
from app.observability.attributes import SemanticAttributes
from app.observability.trace import SpanContext, SpanKind, TraceContext


#: Sort floor for spans whose start is unknown. Never displayed -- only used so
#: `sort` has a total order without `None` comparisons raising.
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _gap_ms(start: datetime | None, end: datetime | None) -> int | None:
    """Milliseconds between two instants, or None if either is missing.

    None rather than 0: an unknown duration and a zero duration are different
    facts, and a trace that renders them identically would tell an operator a
    phase was instantaneous when it is actually still open."""
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds() * 1000))


def _decision_attributes(execution: AgentExecution) -> dict[str, str]:
    """The governing decision a gate node displays (M4-4.2-FR-003).

    Read from what the domain already recorded. `error_message` is included
    because it is the platform's own templated explanation of which rule fired
    (e.g. a concurrency cap, a cost budget) -- authored by this codebase, never
    by a model or an end user, so it is metadata rather than content. Phase 4.3
    will author richer decisions; this surfaces what exists."""
    return {k: v for k, v in {
        "decision": execution.decision,
        "error_code": execution.error_code,
        "reason": execution.error_message,
        "risk_score": str(execution.risk_score) if execution.risk_score is not None else None,
    }.items() if v is not None}


@dataclass
class AssembledSpan:
    """One derived span, with the timings read from its backing row.

    ``source_table``/``source_id`` name the row this was derived from. They are
    not decoration: they are the proof that this span is a *view* of an
    authoritative record, and they let a reader go straight to the row rather
    than wonder whether the telemetry plane and the domain plane agree."""

    span_id: str
    parent_span_id: str | None
    kind: SpanKind
    name: str
    source_table: str | None = None
    source_id: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_ms: int | None = None
    status: str | None = None
    error_code: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "kind": self.kind.value,
            "name": self.name,
            "source_table": self.source_table,
            "source_id": self.source_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error_code": self.error_code,
            "attributes": self.attributes,
        }


@dataclass
class AssembledTrace:
    """A whole trace: its identity, its semantic attributes and its spans."""

    trace_id: str
    execution_id: str
    request_id: str | None
    #: True when the trace id came from a caller-supplied ``correlation_id``
    #: rather than falling back to the execution's own primary key. Surfaced
    #: because it changes what the trace *means*: a derived trace covers one
    #: execution, while a caller-supplied one may span several.
    correlated: bool
    attributes: dict[str, str]
    spans: list[AssembledSpan]
    #: Assembly caveats in plain language (see the module docstring on
    #: multi-attempt tool attribution). Present so a reader is told what the
    #: trace cannot tell them, instead of inferring it wrongly.
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "execution_id": self.execution_id,
            "request_id": self.request_id,
            "correlated": self.correlated,
            "attributes": self.attributes,
            "spans": [span.as_dict() for span in self.spans],
            "notes": self.notes,
        }


class TraceAssembler:
    """Builds a span tree for one execution by reading existing domain rows.

    Read-only by construction -- it holds a ``Session`` but never adds, deletes
    or flushes through it."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def for_execution(self, organization_id: uuid.UUID,
                      execution_id: uuid.UUID) -> AssembledTrace | None:
        """Assemble the trace for one execution, or ``None`` if it is not this
        tenant's. Returning ``None`` rather than raising keeps the tenancy
        decision at the route, where the 404-vs-403 choice belongs."""
        execution = self.db.execute(
            select(AgentExecution).where(
                AgentExecution.id == execution_id,
                AgentExecution.organization_id == organization_id,
            )
        ).scalar_one_or_none()
        if execution is None:
            return None
        return self.assemble(execution)

    def assemble(self, execution: AgentExecution) -> AssembledTrace:
        trace = TraceContext.for_execution(execution)
        root = trace.root_span(SpanKind.EXECUTION, execution.id)
        notes: list[str] = []

        spans: list[AssembledSpan] = [self._execution_span(execution, root)]

        # Phase 4.2 -- the pre-queue phases (SRS 8-4.2). Neither has a table of
        # its own; both are real, externally-meaningful intervals inferred from
        # the execution's own timestamps and terminal codes. They are emitted
        # only when the data actually supports them, so a trace never invents a
        # phase that did not happen.
        spans.extend(self._gate_spans(execution, root))

        approvals = list(self.db.execute(
            select(RuntimeApproval)
            .where(RuntimeApproval.execution_id == execution.id)
            .order_by(RuntimeApproval.created_at)
        ).scalars())
        for approval in approvals:
            spans.append(self._approval_span(approval, root.child(
                SpanKind.APPROVAL, approval.id)))

        attempts = list(self.db.execute(
            select(ExecutionAttempt)
            .where(ExecutionAttempt.execution_id == execution.id)
            .order_by(ExecutionAttempt.attempt_number)
        ).scalars())
        attempt_spans = {
            attempt.id: root.child(SpanKind.ATTEMPT, attempt.id) for attempt in attempts
        }
        for attempt in attempts:
            spans.append(self._attempt_span(attempt, attempt_spans[attempt.id]))

        # A model call is an assistant turn in the loop transcript. The `user`
        # and `tool` rows are the loop's inputs, not calls, so they are not
        # spans -- a span is something that took time and could fail.
        messages = list(self.db.execute(
            select(ExecutionMessage)
            .where(ExecutionMessage.execution_id == execution.id)
            .order_by(ExecutionMessage.sequence)
        ).scalars())
        model_parent = self._single_attempt_span(attempts, attempt_spans, root)
        for message in messages:
            if message.role != "assistant":
                continue
            span = model_parent.child(SpanKind.MODEL_CALL, message.id, message.loop_iteration)
            spans.append(self._model_span(message, span, execution))

        tool_calls = list(self.db.execute(
            select(ToolCall)
            .where(ToolCall.execution_id == execution.id)
            .order_by(ToolCall.created_at)
        ).scalars())
        if tool_calls and len(attempts) > 1:
            notes.append(
                "Tool calls are attached to the execution root rather than to an "
                "attempt: tool_calls records loop_iteration but not attempt_id, so "
                "on a retried execution the owning attempt is not derivable."
            )
        tool_parent = self._single_attempt_span(attempts, attempt_spans, root)
        for call in tool_calls:
            span = tool_parent.child(SpanKind.TOOL_CALL, call.id)
            spans.append(self._tool_span(call, span))
            if call.target_host:
                spans.append(self._external_span(call, span))

        queue_span = self._queue_span(execution, root)
        if queue_span is not None:
            spans.append(queue_span)

        finalization = self._finalization_span(execution, root)
        if finalization is not None:
            spans.append(finalization)

        # Root first, then chronological with unknown-start last. The root is
        # pinned rather than left to sort because it shares its start instant
        # with the authorization gate -- a tie an operator should never see
        # resolved arbitrarily, since a tree's root leading is what makes the
        # rest read as nested beneath it. Nulls last so a phase whose start is
        # unknown (an execution that never left CREATED) does not sort to the
        # front and imply it happened first.
        root_id = root.span_id
        spans.sort(key=lambda s: (s.span_id != root_id,
                                  s.started_at is None,
                                  s.started_at or _EPOCH))

        return AssembledTrace(
            trace_id=trace.trace_id,
            execution_id=str(execution.id),
            request_id=execution.request_id,
            correlated=execution.correlation_id is not None,
            attributes=trace.attributes.as_dict(),
            spans=spans,
            notes=notes,
        )

    # ------------------------------------------------- Phase 4.2 node kinds
    def _gate_spans(self, execution: AgentExecution,
                    root: SpanContext) -> list[AssembledSpan]:
        """The authorization and runtime-policy gates (SRS 8-4.2).

        Both are **computed phases, not rows** -- see this module's docstring on
        why that distinction is reported rather than hidden. What makes them
        derivable at all is that each gate has a distinct terminal signature on
        the execution itself: authorization denial sets `DENIED` with
        `RUNTIME_POLICY_DENIED`, and the runtime policy sets `BLOCKED` with its
        own code. An execution that passed both leaves no denial marker, which
        is exactly how a passing gate is recognized.

        The **governing decision** (M4-4.2-FR-003) is surfaced here where one
        already exists -- `execution.decision` plus the error code that names
        the rule that fired. Phase 4.3 will add richer decisions; this displays
        what the domain already records and authors nothing."""
        spans: list[AssembledSpan] = []
        started = execution.created_at
        ended = execution.queued_at or execution.completed_at

        denied = execution.status == "DENIED"
        blocked = execution.status == "BLOCKED"

        spans.append(AssembledSpan(
            span_id=root.child(SpanKind.AUTHORIZATION).span_id,
            parent_span_id=root.span_id, kind=SpanKind.AUTHORIZATION,
            name="authorization",
            source_table=None, source_id=None,          # a phase, not a row
            started_at=started, ended_at=ended,
            duration_ms=_gap_ms(started, ended),
            status="DENIED" if denied else "ALLOWED",
            error_code=execution.error_code if denied else None,
            attributes=_decision_attributes(execution) if denied else {},
        ))

        # The policy gate only ran if authorization allowed. Emitting it for a
        # DENIED execution would show a phase that never executed.
        if not denied:
            spans.append(AssembledSpan(
                span_id=root.child(SpanKind.RUNTIME_POLICY).span_id,
                parent_span_id=root.span_id, kind=SpanKind.RUNTIME_POLICY,
                name="runtime policy",
                source_table=None, source_id=None,
                started_at=started, ended_at=ended,
                duration_ms=_gap_ms(started, ended),
                status="BLOCKED" if blocked else "PASSED",
                error_code=execution.error_code if blocked else None,
                attributes=_decision_attributes(execution) if blocked else {},
            ))
        return spans

    @staticmethod
    def _queue_span(execution: AgentExecution,
                    root: SpanContext) -> AssembledSpan | None:
        """Time spent QUEUED before a worker claimed it -- a **computed gap**.

        Nothing in this schema records "the queue" as an entity, and 4.1
        deliberately added no table for one. But `queued_at` -> `started_at` is
        a real interval, and in a slow trace it is frequently the largest one:
        an operator asking "why did this take 40 seconds?" is usually looking
        at queue wait, not model latency. Omitting it because no row exists
        would hide the answer to the most common question the trace is opened
        to answer.

        Returns None when the execution never queued (denied at a gate) or has
        not yet been claimed -- an open-ended wait is not a measured duration,
        and reporting one would misrepresent an in-flight execution."""
        if execution.queued_at is None or execution.started_at is None:
            return None
        return AssembledSpan(
            span_id=root.child(SpanKind.QUEUE).span_id,
            parent_span_id=root.span_id, kind=SpanKind.QUEUE,
            name="queue wait",
            source_table=None, source_id=None,
            started_at=execution.queued_at, ended_at=execution.started_at,
            duration_ms=_gap_ms(execution.queued_at, execution.started_at),
            status="CLAIMED",
            attributes={"priority": str(execution.priority)},
        )

    @staticmethod
    def _approval_span(approval: RuntimeApproval, span: SpanContext) -> AssembledSpan:
        """A human approval or challenge. Row-backed by `runtime_approvals`.

        `reason` and `decision_comment` are deliberately not read: they are
        operator-authored free text about the request, which is CONTENT under
        4.1's classification. The trace shows that an approval happened, what
        was asked, who decided and when -- never what anyone wrote."""
        return AssembledSpan(
            span_id=span.span_id, parent_span_id=span.parent_span_id,
            kind=SpanKind.APPROVAL,
            name=f"approval: {approval.requested_action}",
            source_table="runtime_approvals", source_id=str(approval.id),
            started_at=approval.created_at, ended_at=approval.reviewed_at,
            duration_ms=_gap_ms(approval.created_at, approval.reviewed_at),
            status=approval.status,
            attributes={k: v for k, v in {
                "requested_action": approval.requested_action,
                "risk_score": str(approval.risk_score) if approval.risk_score is not None else None,
                "reviewed_by": str(approval.reviewed_by) if approval.reviewed_by else None,
            }.items() if v is not None},
        )

    @staticmethod
    def _finalization_span(execution: AgentExecution,
                           root: SpanContext) -> AssembledSpan | None:
        """Terminal accounting: the outcome, cost and token totals.

        A computed phase. Returns None while the execution is still running --
        an in-flight trace must not show a finalization that has not happened
        (AC-11), because a node claiming a terminal status is precisely the
        torn read that would misrepresent live state."""
        if execution.completed_at is None:
            return None
        return AssembledSpan(
            span_id=root.child(SpanKind.FINALIZATION).span_id,
            parent_span_id=root.span_id, kind=SpanKind.FINALIZATION,
            name=f"finalization ({execution.status})",
            source_table=None, source_id=None,
            started_at=execution.completed_at, ended_at=execution.completed_at,
            duration_ms=0,
            status=execution.status,
            error_code=execution.error_code,
            attributes={k: v for k, v in {
                "cost_amount": str(execution.cost_amount) if execution.cost_amount is not None else None,
                "cost_currency": execution.cost_currency,
                "total_tokens": str(execution.total_tokens) if execution.total_tokens is not None else None,
                "prompt_tokens": str(execution.prompt_tokens) if execution.prompt_tokens is not None else None,
                "completion_tokens": str(execution.completion_tokens) if execution.completion_tokens is not None else None,
                "termination_reason": execution.termination_reason,
                "loop_iterations": str(execution.loop_iterations),
            }.items() if v is not None},
        )

    # ----------------------------------------------------------------- spans
    @staticmethod
    def _single_attempt_span(attempts: list[ExecutionAttempt],
                             attempt_spans: dict[uuid.UUID, SpanContext],
                             root: SpanContext) -> SpanContext:
        """The parent for model/tool spans.

        With exactly one attempt the attribution is unambiguous, so children
        hang off it. With zero or several, they hang off the root -- see the
        module docstring on why guessing would be worse than being vague."""
        if len(attempts) == 1:
            return attempt_spans[attempts[0].id]
        return root

    @staticmethod
    def _execution_span(execution: AgentExecution, span: SpanContext) -> AssembledSpan:
        return AssembledSpan(
            span_id=span.span_id, parent_span_id=None, kind=SpanKind.EXECUTION,
            name=f"execution {execution.status}",
            source_table="agent_executions", source_id=str(execution.id),
            # Phase 4.2: `created_at`, not `started_at`. The root of a trace has
            # to be an envelope around every node beneath it, and 4.2 added
            # gate/queue nodes that begin *before* a worker starts running the
            # execution -- with the old start they rendered outside their own
            # parent, which is incoherent on a timeline.
            started_at=execution.created_at,
            ended_at=execution.completed_at,
            duration_ms=execution.duration_ms,
            status=execution.status,
            error_code=execution.error_code,
            attributes=span.attributes.as_dict(),
        )

    @staticmethod
    def _attempt_span(attempt: ExecutionAttempt, span: SpanContext) -> AssembledSpan:
        return AssembledSpan(
            span_id=span.span_id, parent_span_id=span.parent_span_id, kind=SpanKind.ATTEMPT,
            name=f"attempt {attempt.attempt_number}",
            source_table="execution_attempts", source_id=str(attempt.id),
            started_at=attempt.started_at, ended_at=attempt.completed_at,
            duration_ms=attempt.duration_ms, status=attempt.status,
            error_code=attempt.error_code,
            attributes=SemanticAttributes.build(worker_id=attempt.worker_id).as_dict(),
        )

    @staticmethod
    def _model_span(message: ExecutionMessage, span: SpanContext,
                    execution: AgentExecution) -> AssembledSpan:
        # `content` is deliberately not read. It is the model's output -- the
        # CONTENT data class -- and METADATA_ONLY means a trace shows that a
        # model call happened, how long it took and what it cost, never what it
        # said. See app/observability/capture.py.
        return AssembledSpan(
            span_id=span.span_id, parent_span_id=span.parent_span_id, kind=SpanKind.MODEL_CALL,
            name=f"model call (iteration {message.loop_iteration})",
            source_table="execution_messages", source_id=str(message.id),
            started_at=message.created_at,
            duration_ms=message.duration_ms,
            status=execution.finish_reason,
            attributes=SemanticAttributes.build(
                execution_id=execution.id,
                agent_version_id=execution.agent_version_id,
            ).as_dict(),
        )

    @staticmethod
    def _tool_span(call: ToolCall, span: SpanContext) -> AssembledSpan:
        # `input_summary`/`output_summary` are likewise not read: CONTENT.
        return AssembledSpan(
            span_id=span.span_id, parent_span_id=span.parent_span_id, kind=SpanKind.TOOL_CALL,
            name=f"tool {call.action}",
            source_table="tool_calls", source_id=str(call.id),
            started_at=call.started_at, ended_at=call.completed_at,
            duration_ms=call.duration_ms, status=call.status, error_code=call.error_code,
            attributes=SemanticAttributes.build(
                tool_id=call.tool_id, agent_id=call.agent_id, error_class=call.error_class,
            ).as_dict(),
        )

    @staticmethod
    def _external_span(call: ToolCall, parent: SpanContext) -> AssembledSpan:
        """The egress leg of an HTTP tool call.

        A separate span because it is a separate boundary: the tool call may
        succeed while the external system fails, and one span cannot carry two
        outcomes. Only the *host* is recorded -- never the path or the body,
        both of which can carry a caller-supplied identifier or a token."""
        span = parent.child(SpanKind.EXTERNAL_CALL, call.id)
        return AssembledSpan(
            span_id=span.span_id, parent_span_id=parent.span_id,
            kind=SpanKind.EXTERNAL_CALL,
            name=f"{call.http_method or 'CALL'} {call.target_host}",
            source_table="tool_calls", source_id=str(call.id),
            started_at=call.started_at, ended_at=call.completed_at,
            status=call.egress_decision,
            error_code=call.egress_denied_reason,
            attributes={"target_host": str(call.target_host)},
        )
