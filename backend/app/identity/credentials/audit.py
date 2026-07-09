"""CredentialAuditService — one place every credential event is recorded (SRS §18).

A thin, intention-revealing facade over :class:`SecurityEventService` so the
credential services never assemble raw event rows, and every credential event
carries the same forensic envelope (actor, IP, user agent, request id) as the
rest of the security stream. Events land in ``security_events`` — the platform's
single audit store — rather than a parallel ``credential_events`` table, so the
existing audit UI and export surface them with no new plumbing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.identity.auth.enums import AuthEventType, AuthIdentityType, AuthMethod
from app.identity.auth.security_event_service import SecurityEventService


@dataclass
class CredentialContext:
    """Forensic context recorded on every credential event (SRS §18, §20)."""

    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    correlation_id: str | None = None


class CredentialAuditService:
    def __init__(self, db: Session) -> None:
        self.events = SecurityEventService(db)

    def record(
        self,
        event_type: AuthEventType,
        *,
        organization_id: uuid.UUID | None,
        identity_id: uuid.UUID | None,
        actor_id: uuid.UUID | None = None,
        context: CredentialContext | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        ctx = context or CredentialContext()
        meta = dict(metadata or {})
        if actor_id is not None and actor_id != identity_id:
            # An administrator acting on someone else's credential (SRS §16).
            meta.setdefault("actor_id", str(actor_id))
        self.events.record(
            event_type,
            auth_method=AuthMethod.PASSWORD,
            identity_type=AuthIdentityType.HUMAN_USER.value,
            organization_id=organization_id,
            identity_id=identity_id,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            request_id=ctx.request_id,
            correlation_id=ctx.correlation_id,
            metadata=meta,
        )
