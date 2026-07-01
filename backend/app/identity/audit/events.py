"""Identity audit/security event recording (SRS §9 audit, §19).

Every identity action records a ``SecurityEvent`` (identity-specific stream) and,
when tied to an organization, mirrors a platform ``audit_logs`` entry so identity
activity shows up in the existing Audit & Compliance Center. Records are staged
(flushed) but the caller owns the commit.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import ActorType
from app.identity.models.enums import IdentityType, SecurityEventType
from app.identity.models.security_event import SecurityEvent
from app.services import audit_service

# Identity actor type → platform ActorType for the mirrored audit log.
_ACTOR_MAP = {
    IdentityType.HUMAN: ActorType.USER,
    IdentityType.AI_AGENT: ActorType.AGENT,
    IdentityType.SERVICE_ACCOUNT: ActorType.SYSTEM,
    IdentityType.EXTERNAL_CLIENT: ActorType.SYSTEM,
    IdentityType.ORGANIZATION: ActorType.SYSTEM,
}


def record_security_event(
    db: Session,
    *,
    event_type: SecurityEventType | str,
    actor_type: IdentityType,
    organization_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    request_id: str | None = None,
    correlation_id: str | None = None,
    ip_address: str | None = None,
    metadata: dict[str, Any] | None = None,
    mirror_to_audit_log: bool = True,
) -> SecurityEvent:
    """Record a security event (+ optional mirrored platform audit log)."""
    code = event_type.value if isinstance(event_type, SecurityEventType) else str(event_type)
    event = SecurityEvent(
        organization_id=organization_id,
        event_type=code,
        actor_type=actor_type.value,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        request_id=request_id,
        correlation_id=correlation_id,
        ip_address=ip_address,
        meta=metadata or {},
    )
    db.add(event)
    db.flush()

    if mirror_to_audit_log and organization_id is not None:
        audit_service.log_event(
            db,
            organization_id=organization_id,
            actor_type=_ACTOR_MAP.get(actor_type, ActorType.SYSTEM),
            actor_id=actor_id,
            event_type=f"IDENTITY_{code}",
            entity_type=target_type or "identity",
            entity_id=target_id,
            metadata=metadata or {},
            request_id=request_id,
            trace_id=correlation_id,
        )
    return event
