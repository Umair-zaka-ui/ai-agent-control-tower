"""Audit service - the single entry point for writing audit log entries.

The new ``AuditLog`` is added to the session and flushed so its id is available,
but the surrounding transaction is committed by the caller. This keeps the audit
record atomic with the business operation it describes.

Phase 2 adds forensic context (ip address, user agent, request/trace ids) and
optional before/after state snapshots.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import ActorType
from app.models.audit_log import AuditLog


def log_event(
    db: Session,
    *,
    organization_id: uuid.UUID,
    actor_type: ActorType,
    event_type: str,
    entity_type: str,
    actor_id: uuid.UUID | None = None,
    entity_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
) -> AuditLog:
    """Create and stage an audit log entry. Does not commit."""
    log = AuditLog(
        organization_id=organization_id,
        actor_type=actor_type,
        actor_id=actor_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        meta=metadata or {},
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
        trace_id=trace_id,
        before_state=before_state,
        after_state=after_state,
    )
    db.add(log)
    db.flush()
    return log
