"""Department aggregate repository (SRS §16)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.identity.models.department import Department, Team
from app.identity.repositories.base import BaseRepository


class DepartmentRepository(BaseRepository[Department]):
    model = Department

    def list_by_organization(self, organization_id: uuid.UUID) -> list[Department]:
        stmt = (
            select(Department)
            .where(Department.organization_id == organization_id)
            .order_by(Department.name)
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_teams(self, department_id: uuid.UUID) -> list[Team]:
        stmt = select(Team).where(Team.department_id == department_id).order_by(Team.name)
        return list(self.db.execute(stmt).scalars().all())
