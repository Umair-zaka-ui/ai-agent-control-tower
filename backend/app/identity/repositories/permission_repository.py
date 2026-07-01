"""Permission catalog repository (SRS §16). Reuses ``rbac_permissions``."""

from __future__ import annotations

from sqlalchemy import select

from app.identity.repositories.base import BaseRepository
from app.models.rbac import RbacPermission


class PermissionRepository(BaseRepository[RbacPermission]):
    model = RbacPermission

    def get_by_code(self, code: str) -> RbacPermission | None:
        return self.db.execute(
            select(RbacPermission).where(RbacPermission.code == code)
        ).scalar_one_or_none()

    def all_codes(self) -> list[str]:
        return list(self.db.execute(select(RbacPermission.code)).scalars().all())
