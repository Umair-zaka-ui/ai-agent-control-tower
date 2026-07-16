"""Middleware audit integration (Phase 4.3.6 §24, §35).

Emits the six pipeline events into the platform audit trail:

    AUTHORIZATION_STARTED     evaluation began (skipped on decision-cache hits —
                              a cache hit replays an already-audited decision)
    DECISION_GENERATED        the normalized decision, with the pipeline trace
    OBLIGATIONS_APPLIED       obligations were processed
    AUTHORIZATION_COMPLETED   pipeline finished with an allowing decision
    AUTHORIZATION_FAILED      pipeline finished with a deny/challenge, or errored
    EXECUTION_COMPLETED       the enforcement point finished the business action

Sensitive attribute values are never logged here — only decision metadata,
matched policy ids and the stage trace (§35, §36).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import ActorType
from app.services import audit_service

_ACTOR_TYPES = {"USER": ActorType.USER, "AGENT": ActorType.AGENT, "SYSTEM": ActorType.SYSTEM}


class AuthorizationAuditService:
    """§21, §24 — one writer for every pipeline audit event."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _emit(self, event: str, *, organization_id: uuid.UUID | None,
              identity_id: uuid.UUID | None, identity_kind: str,
              request_id: str | None, correlation_id: str | None,
              meta: dict[str, Any]) -> None:
        if organization_id is None:
            return  # audit_logs is org-anchored; org-less principals have no anchor
        audit_service.log_event(
            self.db,
            organization_id=organization_id,
            actor_type=_ACTOR_TYPES.get(identity_kind, ActorType.SYSTEM),
            actor_id=identity_id,
            event_type=event,
            entity_type="authorization",
            request_id=request_id,
            trace_id=correlation_id,
            metadata=meta,
        )

    def started(self, ctx) -> None:
        self._emit("AUTHORIZATION_STARTED",
                   organization_id=ctx.organization_id, identity_id=ctx.identity_id,
                   identity_kind=ctx.identity_kind, request_id=ctx.request_id,
                   correlation_id=ctx.correlation_id,
                   meta={"permission": ctx.permission, "action": ctx.action,
                         "resource_type": ctx.resource_type,
                         "resource_id": str(ctx.resource_id) if ctx.resource_id else None,
                         "source": ctx.source})

    def decision_generated(self, ctx, decision: dict[str, Any],
                           trace: list[dict]) -> None:
        self._emit("DECISION_GENERATED",
                   organization_id=ctx.organization_id, identity_id=ctx.identity_id,
                   identity_kind=ctx.identity_kind, request_id=ctx.request_id,
                   correlation_id=ctx.correlation_id,
                   meta={"permission": ctx.permission, "decision": decision.get("decision"),
                         "allowed": decision.get("allowed"),
                         "matched_policies": decision.get("matched_policies", []),
                         "evaluation_time_ms": decision.get("evaluation_time_ms"),
                         "pipeline_trace": trace, "source": ctx.source})

    def obligations_applied(self, ctx, obligations: list[dict]) -> None:
        self._emit("OBLIGATIONS_APPLIED",
                   organization_id=ctx.organization_id, identity_id=ctx.identity_id,
                   identity_kind=ctx.identity_kind, request_id=ctx.request_id,
                   correlation_id=ctx.correlation_id,
                   meta={"permission": ctx.permission,
                         "obligations": [o.get("type") for o in obligations]})

    def completed(self, ctx, decision: dict[str, Any]) -> None:
        self._emit("AUTHORIZATION_COMPLETED",
                   organization_id=ctx.organization_id, identity_id=ctx.identity_id,
                   identity_kind=ctx.identity_kind, request_id=ctx.request_id,
                   correlation_id=ctx.correlation_id,
                   meta={"permission": ctx.permission, "decision": decision.get("decision"),
                         "evaluation_time_ms": decision.get("evaluation_time_ms")})

    def failed(self, ctx, decision: dict[str, Any] | None = None,
               error: str | None = None) -> None:
        self._emit("AUTHORIZATION_FAILED",
                   organization_id=ctx.organization_id, identity_id=ctx.identity_id,
                   identity_kind=ctx.identity_kind, request_id=ctx.request_id,
                   correlation_id=ctx.correlation_id,
                   meta={"permission": ctx.permission,
                         "decision": (decision or {}).get("decision"),
                         "reason": (decision or {}).get("reason"), "error": error})

    def execution_completed(self, ctx, *, outcome: str,
                            detail: dict[str, Any] | None = None) -> None:
        """Called by the enforcement point after the business action ran."""
        self._emit("EXECUTION_COMPLETED",
                   organization_id=ctx.organization_id, identity_id=ctx.identity_id,
                   identity_kind=ctx.identity_kind, request_id=ctx.request_id,
                   correlation_id=ctx.correlation_id,
                   meta={"permission": ctx.permission, "outcome": outcome,
                         **(detail or {})})
