"""Authorization decision audit (Phase 4.3.2 §18, §20, §27).

Persists evaluated decisions to ``authorization_decisions`` with timing. Denials
are always recorded (security-relevant); grants on the high-volume gate path are
recorded only when ``AUTHZ_LOG_ALLOW_DECISIONS`` is on, to protect the <5ms
middleware budget (§25). The ``/authorization/check`` endpoint always records.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.authorization.engine import AuthorizationResult
from app.core.config import settings
from app.models.rbac import AuthorizationDecision
from app.models.user import User


class AuthorizationDecisionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def record(
        self,
        user: User,
        result: AuthorizationResult,
        *,
        request_id: str | None = None,
        evaluation_time_ms: float | None = None,
        force: bool = False,
    ) -> AuthorizationDecision | None:
        """Persist a decision. Skips ALLOWs on the gate path unless configured or
        ``force`` (the explicit check endpoint forces it). Best-effort — never let
        an audit write break the request."""
        if result.allowed and not force and not settings.AUTHZ_LOG_ALLOW_DECISIONS:
            return None
        row = AuthorizationDecision(
            identity_id=user.id,
            organization_id=user.organization_id,
            permission=result.permission,
            resource_type=result.resource_type,
            resource_id=result.resource_id,
            allowed=result.allowed,
            reason=result.reason,
            scope=result.scope,
            source_role=result.source_role,
            evaluation_time_ms=evaluation_time_ms,
            request_id=request_id,
        )
        try:
            self.db.add(row)
            self.db.commit()
            return row
        except Exception:
            self.db.rollback()
            return None
