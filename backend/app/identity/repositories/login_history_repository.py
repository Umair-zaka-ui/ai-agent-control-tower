"""Login history repository (SRS §13, §15)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select

from app.identity.models.login_history import LoginHistory
from app.identity.repositories.base import BaseRepository


class LoginHistoryRepository(BaseRepository[LoginHistory]):
    model = LoginHistory

    def count_recent_failures(self, email: str, since: datetime) -> int:
        """Failed attempts for an email since ``since`` (the lockout window)."""
        stmt = select(func.count()).select_from(LoginHistory).where(
            func.lower(LoginHistory.email) == email.lower(),
            LoginHistory.success.is_(False),
            LoginHistory.created_at >= since,
        )
        return int(self.db.execute(stmt).scalar_one())

    def last_success(self, user_id: uuid.UUID) -> LoginHistory | None:
        stmt = (
            select(LoginHistory)
            .where(LoginHistory.user_id == user_id, LoginHistory.success.is_(True))
            .order_by(LoginHistory.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_for_user(self, user_id: uuid.UUID, *, limit: int = 50) -> list[LoginHistory]:
        stmt = (
            select(LoginHistory)
            .where(LoginHistory.user_id == user_id)
            .order_by(LoginHistory.created_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())
