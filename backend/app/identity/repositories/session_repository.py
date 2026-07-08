"""Session aggregate repository (SRS 4.2.2.2 §22).

Pure data access. Every method that answers "is this session usable?" returns
rows; the *decision* lives in ``SessionLifecycleService`` so the clock is applied
in exactly one place.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from app.identity.models.enums import SessionStatus
from app.identity.models.session import UserSession
from app.identity.repositories.base import BaseRepository

# States that still permit authentication; anything else is terminal.
_LIVE_STATES = (
    SessionStatus.CREATED.value,
    SessionStatus.ACTIVE.value,
    SessionStatus.IDLE.value,
)


class SessionRepository(BaseRepository[UserSession]):
    model = UserSession

    def list_active_for_user(self, user_id: uuid.UUID) -> list[UserSession]:
        """Sessions that are neither revoked nor terminal, newest first."""
        stmt = (
            select(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.status.in_(_LIVE_STATES),
            )
            .order_by(UserSession.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_for_user(self, user_id: uuid.UUID, *, limit: int = 50) -> list[UserSession]:
        """All sessions, live or not — the audit view."""
        stmt = (
            select(UserSession)
            .where(UserSession.user_id == user_id)
            .order_by(UserSession.created_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def count_active_for_user(self, user_id: uuid.UUID) -> int:
        return len(self.list_active_for_user(user_id))

    def oldest_active_for_user(self, user_id: uuid.UUID) -> UserSession | None:
        """Used to enforce the concurrent-session limit (SRS §11)."""
        stmt = (
            select(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.status.in_(_LIVE_STATES),
            )
            .order_by(UserSession.created_at.asc())
            .limit(1)
        )
        return self.db.execute(stmt).scalars().first()

    def list_expired(self, now: datetime, *, limit: int = 500) -> list[UserSession]:
        """Live sessions whose clock has run out — for the reaper (SRS §5)."""
        stmt = (
            select(UserSession)
            .where(
                UserSession.status.in_(_LIVE_STATES),
                UserSession.revoked_at.is_(None),
                (UserSession.absolute_expires_at <= now) | (UserSession.idle_expires_at <= now),
            )
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_by_family(self, family_id: uuid.UUID) -> list[UserSession]:
        stmt = select(UserSession).where(UserSession.refresh_token_family_id == family_id)
        return list(self.db.execute(stmt).scalars().all())

    def has_seen_country(self, user_id: uuid.UUID, country: str) -> bool:
        """Has this user ever had a session from this country? (SRS §15 scoring)"""
        stmt = (
            select(UserSession.id)
            .where(UserSession.user_id == user_id, UserSession.country == country)
            .limit(1)
        )
        return self.db.execute(stmt).scalars().first() is not None
