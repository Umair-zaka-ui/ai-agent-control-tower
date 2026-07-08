"""RegistrationAuditService — one place that records onboarding events (§7, §13, §20).

Every registration action records what §20 demands: request id, correlation id, actor
(where one exists), target email, organization, timestamp, IP address and user agent.

The target email is recorded **in full**. This is an internal security-event stream,
not a log aggregator, and an invitation audit trail that redacts the invitee is
useless — the whole question an auditor asks is *who was invited*.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.identity.auth.enums import AuthEventType, AuthMethod
from app.identity.auth.security_event_service import SecurityEventService


@dataclass(frozen=True)
class RequestContext:
    """Forensic context for one onboarding request (§20)."""

    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    correlation_id: str | None = None


class RegistrationAuditService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.events = SecurityEventService(db)

    def record(
        self,
        event: AuthEventType,
        *,
        organization_id: uuid.UUID | None,
        target_email: str,
        actor_id: uuid.UUID | None = None,
        context: RequestContext | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        context = context or RequestContext()
        self.events.record(
            event,
            auth_method=AuthMethod.PASSWORD,
            identity_type="HUMAN_USER",
            organization_id=organization_id,
            # `actor_id` is the administrator for invitation events and the user for
            # registration/verification events. `target_email` is who it happened to.
            identity_id=actor_id,
            ip_address=context.ip_address,
            user_agent=context.user_agent,
            request_id=context.request_id,
            correlation_id=context.correlation_id,
            metadata={"target_email": target_email, **(metadata or {})},
        )
