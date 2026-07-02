"""SecurityEventService — record authentication/security events (SRS §13, §16).

Wraps the identity ``record_security_event`` recorder, adding the ``auth_method``
to the event metadata so every authentication action is auditable.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.identity.audit.events import record_security_event
from app.identity.auth.enums import AuthEventType, AuthMethod
from app.identity.models.enums import IdentityType
from app.identity.models.security_event import SecurityEvent

# Auth identity type → domain IdentityType for the mirrored platform audit log.
_DOMAIN_ACTOR = {
    "HUMAN_USER": IdentityType.HUMAN,
    "AI_AGENT": IdentityType.AI_AGENT,
    "SERVICE_ACCOUNT": IdentityType.SERVICE_ACCOUNT,
    "EXTERNAL_CLIENT": IdentityType.EXTERNAL_CLIENT,
    "SYSTEM": IdentityType.ORGANIZATION,
}


class SecurityEventService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def record(
        self,
        event_type: AuthEventType,
        *,
        auth_method: AuthMethod,
        identity_type: str,
        organization_id: uuid.UUID | None = None,
        identity_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SecurityEvent:
        meta = {"auth_method": auth_method.value, **(metadata or {})}
        if user_agent:
            meta.setdefault("user_agent", user_agent)
        return record_security_event(
            self.db,
            event_type=event_type.value,
            actor_type=_DOMAIN_ACTOR.get(identity_type, IdentityType.ORGANIZATION),
            organization_id=organization_id,
            actor_id=identity_id,
            target_type=identity_type,
            target_id=identity_id,
            request_id=request_id,
            correlation_id=correlation_id,
            ip_address=ip_address,
            metadata=meta,
            # Auth events are their own stream; avoid doubling every login into
            # the business audit log.
            mirror_to_audit_log=False,
        )
