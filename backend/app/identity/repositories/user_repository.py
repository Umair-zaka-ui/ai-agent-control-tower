"""User aggregate repository (SRS §16)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.identity.repositories.base import BaseRepository
from app.models.user import User


class UserRepository(BaseRepository[User]):
    model = User

    def get_by_email(self, email: str) -> User | None:
        return self.db.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()

    def list_by_organization(
        self, organization_id: uuid.UUID, *, limit: int = 100, offset: int = 0
    ) -> list[User]:
        stmt = (
            select(User)
            .where(User.organization_id == organization_id)
            .order_by(User.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_by_department(self, department_id: uuid.UUID) -> list[User]:
        return list(
            self.db.execute(
                select(User).where(User.department_id == department_id)
            ).scalars().all()
        )
