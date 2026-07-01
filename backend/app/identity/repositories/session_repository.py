"""Session aggregate repository (SRS §16)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.identity.models.session import UserSession
from app.identity.repositories.base import BaseRepository


class SessionRepository(BaseRepository[UserSession]):
    model = UserSession

    def list_active_for_user(self, user_id: uuid.UUID) -> list[UserSession]:
        stmt = (
            select(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .order_by(UserSession.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())
