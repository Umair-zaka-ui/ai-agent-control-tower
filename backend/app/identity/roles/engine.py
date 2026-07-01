"""Role engine — assign/revoke/list roles (SRS §9 roles).

Uses namespaced role names (e.g. ROLE_SUPER_ADMIN) and the existing RBAC join
table ``user_roles``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.repositories.role_repository import RoleRepository
from app.models.rbac import Role, UserRole


class RoleEngine:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.roles = RoleRepository(db)

    def list_for_organization(self, organization_id: uuid.UUID) -> list[Role]:
        return self.roles.list_for_organization(organization_id)

    def roles_for_user(self, user_id: uuid.UUID) -> list[Role]:
        stmt = (
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        )
        return list(self.db.execute(stmt).scalars().all())

    def assign(self, user_id: uuid.UUID, role_id: uuid.UUID) -> UserRole:
        """Idempotently assign a role to a user. Stages; caller commits."""
        existing = self.db.execute(
            select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role_id)
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        link = UserRole(user_id=user_id, role_id=role_id)
        self.db.add(link)
        self.db.flush()
        return link

    def revoke(self, user_id: uuid.UUID, role_id: uuid.UUID) -> bool:
        link = self.db.execute(
            select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role_id)
        ).scalar_one_or_none()
        if link is None:
            return False
        self.db.delete(link)
        self.db.flush()
        return True
