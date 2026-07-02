"""SessionService — session lifecycle for human logins (SRS §15, §16).

Thin, auth-oriented facade over the identity ``SessionManager`` so the
authentication layer has one entry point for create / touch / list / revoke /
expire.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.identity.models.session import UserSession
from app.identity.sessions.manager import SessionManager


class SessionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._manager = SessionManager(db)

    def create(
        self,
        user_id: uuid.UUID,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> UserSession:
        return self._manager.create(user_id, ip_address=ip_address, user_agent=user_agent)

    def touch(self, session: UserSession) -> UserSession:
        """Update ``last_seen_at`` on activity."""
        session.last_seen_at = datetime.now(timezone.utc)
        self.db.flush()
        return session

    def list_active(self, user_id: uuid.UUID) -> list[UserSession]:
        return self._manager.list_active(user_id)

    def revoke(self, session: UserSession) -> UserSession:
        return self._manager.revoke(session)

    def is_active(self, session: UserSession) -> bool:
        return SessionManager.is_active(session)
