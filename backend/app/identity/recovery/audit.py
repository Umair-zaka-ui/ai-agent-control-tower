"""RecoveryAuditService — one place recovery events are recorded (4.2.2.3.3 §24).

Recovery events land in the platform's single ``security_events`` stream, not a
separate ``recovery_events`` table (§5): the existing audit UI, export and
``GET /security/recovery-events`` all read that stream, so a parallel table would
be plumbing rebuilt for no gain. Every event carries the §26 forensic envelope
(actor, IP, user agent, request id) and the target email, never a token.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.identity.auth.enums import AuthEventType, AuthIdentityType, AuthMethod
from app.identity.auth.security_event_service import SecurityEventService


@dataclass(frozen=True)
class RecoveryContext:
    """Forensic context for one recovery request (§26)."""

    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    correlation_id: str | None = None


class RecoveryAuditService:
    def __init__(self, db: Session) -> None:
        self.events = SecurityEventService(db)

    def record(
        self,
        event: AuthEventType,
        *,
        organization_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        target_email: str | None = None,
        context: RecoveryContext | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        ctx = context or RecoveryContext()
        meta = dict(metadata or {})
        if target_email:
            meta.setdefault("target_email", target_email)
        self.events.record(
            event,
            auth_method=AuthMethod.PASSWORD,
            identity_type=AuthIdentityType.HUMAN_USER.value,
            organization_id=organization_id,
            identity_id=user_id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            request_id=ctx.request_id,
            correlation_id=ctx.correlation_id,
            metadata=meta,
        )
