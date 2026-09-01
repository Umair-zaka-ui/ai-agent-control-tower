"""Phase 4.8 -- the governed trace-content store (M4-4.8-FR-010..012, FR-023).

Content is **materialised on the first authorised view and never before**. A
``METADATA_ONLY`` or ``DISABLED`` scope materialises nothing -- that is the
"captures no content" / "captures nothing" guarantee, and a test asserts
``trace_content`` stays empty after a view under those modes.

When a mode permits content, every source value goes through
:func:`app.telemetry_privacy.redaction.redact_for_capture` -- strip reasoning
(§7), scrub secrets (§14), then classification-mask for ``REDACTED_CONTENT`` --
**before** the row is inserted. The insert is idempotent
(``uq_trace_content_source``), so a second view is a read, not a re-capture.

This module reads domain rows but the ``trace_content`` copy it writes has its
own lifetime: :mod:`app.telemetry_privacy.retention` expires it while the domain
rows and the execution itself persist (M4-4.8-FR-032).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.runtime import (
    AgentExecution,
    ExecutionMessage,
    ToolCall,
    TraceContent,
)
from app.observability.trace import TraceContext
from app.telemetry_privacy.modes import is_disabled, permits_content
from app.telemetry_privacy.policy import EffectiveMode, resolve_for_execution
from app.telemetry_privacy.redaction import redact_for_capture


class TraceContentService:
    """Resolve capture policy, materialise governed content, and read it back.

    Read + write on the telemetry plane only. Nothing here touches an execution
    row, takes a lock on one, or can affect one (§9)."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    def view(self, organization_id: uuid.UUID,
             execution: AgentExecution) -> dict:
        """The content view for one execution (M4-4.8-FR-021).

        Returns the effective mode and its explanation always; the content
        items only when the mode permits content. Under ``METADATA_ONLY`` /
        ``DISABLED`` the ``items`` list is empty and ``captured`` is ``False``
        -- the honest answer, not an error."""
        effective = resolve_for_execution(self.db, execution)
        payload: dict = {
            "execution_id": str(execution.id),
            "mode": effective.mode.value,
            "policy": effective.as_dict(),
            "captured": False,
            "items": [],
        }
        if is_disabled(effective.mode):
            payload["note"] = (
                "Telemetry is DISABLED for this scope: no content and no derived "
                "telemetry event is recorded.")
            return payload
        if not permits_content(effective.mode):
            payload["note"] = (
                "Capture mode is METADATA_ONLY: no execution content is captured. "
                "Enable REDACTED_CONTENT or FULL_CONTENT for this scope to capture it.")
            return payload

        self.materialize(execution, effective)
        rows = list(self.db.execute(
            select(TraceContent)
            .where(TraceContent.execution_id == execution.id,
                   TraceContent.organization_id == organization_id)
            .order_by(TraceContent.source_table, TraceContent.sequence)
        ).scalars())
        payload["captured"] = True
        payload["items"] = [self._item(r) for r in rows]
        return payload

    @staticmethod
    def _item(row: TraceContent) -> dict:
        return {
            "id": str(row.id),
            "source_table": row.source_table,
            "source_id": str(row.source_id) if row.source_id else None,
            "sequence": row.sequence,
            "role": row.role,
            "classification": row.classification,
            "mode_applied": row.mode_applied,
            "redacted": row.redacted,
            "secret_scrubbed": row.secret_scrubbed,
            "body": row.body,
            "captured_at": row.created_at.isoformat() if row.created_at else None,
        }

    # ------------------------------------------------------------------ #
    def materialize(self, execution: AgentExecution,
                    effective: EffectiveMode | None = None) -> int:
        """Idempotently write the governed content rows for one execution.

        Returns the number of rows inserted this call (0 on a re-run, or when
        the mode does not permit content). Never raises on a telemetry-plane
        problem -- a caller on a read path stays a read path."""
        effective = effective or resolve_for_execution(self.db, execution)
        mode = effective.mode
        if not permits_content(mode):
            return 0

        classification = effective.matched_scope.get("classification")
        trace_id = None
        try:
            trace_id = TraceContext.for_execution(execution).trace_id
        except Exception:  # pragma: no cover - defensive; trace id is best-effort
            trace_id = execution.correlation_id or str(execution.id)

        inserted = 0
        for source_table, source_id, sequence, role, raw in self._sources(execution):
            if raw is None or raw == {} or raw == []:
                continue
            result = redact_for_capture(
                raw, mode=mode.value, classification=classification)
            stmt = insert(TraceContent).values(
                id=uuid.uuid4(),
                organization_id=execution.organization_id,
                execution_id=execution.id,
                trace_id=trace_id,
                source_table=source_table,
                source_id=source_id,
                sequence=sequence,
                role=role,
                classification=classification,
                mode_applied=mode.value,
                redacted=result.redacted,
                secret_scrubbed=result.secret_scrubbed,
                body={"value": result.body},
            ).on_conflict_do_nothing(constraint="uq_trace_content_source")
            if self.db.execute(stmt).rowcount:
                inserted += 1
        if inserted:
            self.db.commit()
        return inserted

    def _sources(self, execution: AgentExecution):
        """Yield ``(source_table, source_id, sequence, role, raw_value)`` for
        every domain location that carries content for this execution.

        The order (``agent_executions`` then ``execution_messages`` then
        ``tool_calls``) plus ``sequence`` is what the view sorts by."""
        yield ("agent_executions", execution.id, 0, "input", execution.input_payload)
        yield ("agent_executions", execution.id, 1, "output", execution.output_payload)

        messages = list(self.db.execute(
            select(ExecutionMessage)
            .where(ExecutionMessage.execution_id == execution.id)
            .order_by(ExecutionMessage.sequence)
        ).scalars())
        for message in messages:
            body = {
                "role": message.role,
                "content": message.content,
                "tool_name": message.tool_name,
                "tool_calls_requested": message.tool_calls_requested,
            }
            yield ("execution_messages", message.id, message.sequence, message.role, body)

        calls = list(self.db.execute(
            select(ToolCall)
            .where(ToolCall.execution_id == execution.id)
            .order_by(ToolCall.created_at)
        ).scalars())
        for index, call in enumerate(calls):
            body = {
                "action": call.action,
                "input_summary": call.input_summary,
                "output_summary": call.output_summary,
                "validation_error": call.validation_error,
            }
            yield ("tool_calls", call.id, index, "tool", body)
