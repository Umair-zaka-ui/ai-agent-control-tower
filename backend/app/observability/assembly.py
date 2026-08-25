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
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.runtime import (
    AgentExecution,
    ExecutionAttempt,
    ExecutionMessage,
    ToolCall,
)
from app.observability.attributes import SemanticAttributes
from app.observability.trace import SpanContext, SpanKind, TraceContext


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

        return AssembledTrace(
            trace_id=trace.trace_id,
            execution_id=str(execution.id),
            request_id=execution.request_id,
            correlated=execution.correlation_id is not None,
            attributes=trace.attributes.as_dict(),
            spans=spans,
            notes=notes,
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
            started_at=execution.started_at or execution.queued_at or execution.created_at,
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
