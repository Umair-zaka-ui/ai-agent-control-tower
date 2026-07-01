"""Role aggregate repository (SRS §16). Reuses the existing RBAC roles table."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select

from app.identity.repositories.base import BaseRepository
from app.models.rbac import Role


class RoleRepository(BaseRepository[Role]):
    model = Role

    def get_by_name(self, name: str, organization_id: uuid.UUID | None = None) -> Role | None:
        stmt = select(Role).where(Role.name == name)
        if organization_id is not None:
            stmt = stmt.where(
                or_(Role.organization_id == organization_id, Role.organization_id.is_(None))
            )
        return self.db.execute(stmt).scalars().first()

    def list_for_organization(self, organization_id: uuid.UUID) -> list[Role]:
        """System roles (organization_id NULL) plus the org's own roles."""
        stmt = select(Role).where(
            or_(Role.organization_id == organization_id, Role.organization_id.is_(None))
        )
        return list(self.db.execute(stmt).scalars().all())
