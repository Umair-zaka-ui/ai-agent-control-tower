"""Session manager — create, list and revoke sessions (SRS §9 sessions)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.identity.models.session import UserSession
from app.identity.repositories.session_repository import SessionRepository

DEFAULT_SESSION_TTL = timedelta(hours=12)


class SessionManager:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.sessions = SessionRepository(db)

    def create(
        self,
        user_id: uuid.UUID,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
        ttl: timedelta = DEFAULT_SESSION_TTL,
    ) -> UserSession:
        now = datetime.now(timezone.utc)
        session = UserSession(
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=now,
            expires_at=now + ttl,
            last_seen_at=now,
        )
        return self.sessions.add(session)

    def list_active(self, user_id: uuid.UUID) -> list[UserSession]:
        return self.sessions.list_active_for_user(user_id)

    def revoke(self, session: UserSession) -> UserSession:
        session.revoked_at = datetime.now(timezone.utc)
        self.db.flush()
        return session

    @staticmethod
    def is_active(session: UserSession) -> bool:
        if session.revoked_at is not None:
            return False
        return session.expires_at > datetime.now(timezone.utc)
