"""Authorization repositories (Phase 4.3.1 §19).

Thin data-access objects over the RBAC tables. No business rules here — services
own validation, cycle detection and audit.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.rbac import (
    AuthorizationAudit,
    PermissionGroup,
    RbacPermission,
    Role,
    RoleHierarchy,
    RolePermission,
    UserRole,
)


class RoleRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, role_id: uuid.UUID) -> Role | None:
        return self.db.get(Role, role_id)

    def get_visible(self, role_id: uuid.UUID, organization_id: uuid.UUID | None) -> Role | None:
        """A role the org may see: its own, or a global (system) role."""
        role = self.db.get(Role, role_id)
        if role is None:
            return None
        if role.organization_id is None or role.organization_id == organization_id:
            return role
        return None

    def get_by_name(self, organization_id: uuid.UUID | None, name: str) -> Role | None:
        stmt = select(Role).where(Role.name == name)
        stmt = stmt.where(
            Role.organization_id.is_(None)
            if organization_id is None
            else Role.organization_id == organization_id
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_visible(
        self,
        organization_id: uuid.UUID | None,
        *,
        category: str | None = None,
        status: str | None = None,
        search: str | None = None,
    ) -> list[Role]:
        stmt = select(Role).where(
            or_(Role.organization_id == organization_id, Role.organization_id.is_(None))
        )
        if category:
            stmt = stmt.where(Role.category == category)
        if status:
            stmt = stmt.where(Role.status == status)
        if search:
            like = f"%{search.lower()}%"
            stmt = stmt.where(
                or_(func.lower(Role.name).like(like), func.lower(Role.display_name).like(like))
            )
        stmt = stmt.order_by(Role.priority.desc(), Role.name)
        return list(self.db.execute(stmt).scalars().all())

    def add(self, role: Role) -> Role:
        self.db.add(role)
        self.db.flush()
        return role

    def assignment_count(self, role_id: uuid.UUID) -> int:
        return self.db.execute(
            select(func.count()).select_from(UserRole).where(UserRole.role_id == role_id)
        ).scalar_one()


class PermissionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, permission_id: uuid.UUID) -> RbacPermission | None:
        return self.db.get(RbacPermission, permission_id)

    def get_by_code(self, code: str) -> RbacPermission | None:
        return self.db.execute(
            select(RbacPermission).where(RbacPermission.code == code)
        ).scalar_one_or_none()

    def list(self, *, group_id: uuid.UUID | None = None, search: str | None = None) -> list[RbacPermission]:
        stmt = select(RbacPermission)
        if group_id:
            stmt = stmt.where(RbacPermission.group_id == group_id)
        if search:
            like = f"%{search.lower()}%"
            stmt = stmt.where(func.lower(RbacPermission.code).like(like))
        return list(self.db.execute(stmt.order_by(RbacPermission.code)).scalars().all())

    def add(self, permission: RbacPermission) -> RbacPermission:
        self.db.add(permission)
        self.db.flush()
        return permission

    def role_grant_count(self, permission_id: uuid.UUID) -> int:
        return self.db.execute(
            select(func.count()).select_from(RolePermission).where(
                RolePermission.permission_id == permission_id
            )
        ).scalar_one()


class PermissionGroupRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, group_id: uuid.UUID) -> PermissionGroup | None:
        return self.db.get(PermissionGroup, group_id)

    def list(self) -> list[PermissionGroup]:
        return list(
            self.db.execute(
                select(PermissionGroup).order_by(PermissionGroup.sort_order, PermissionGroup.name)
            ).scalars().all()
        )


class RoleAssignmentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, assignment_id: uuid.UUID) -> UserRole | None:
        return self.db.get(UserRole, assignment_id)

    def list(
        self,
        *,
        user_id: uuid.UUID | None = None,
        role_id: uuid.UUID | None = None,
        scope: str | None = None,
        include_expired: bool = True,
    ) -> list[UserRole]:
        stmt = select(UserRole)
        if user_id:
            stmt = stmt.where(UserRole.user_id == user_id)
        if role_id:
            stmt = stmt.where(UserRole.role_id == role_id)
        if scope:
            stmt = stmt.where(UserRole.scope == scope)
        if not include_expired:
            now = datetime.now(timezone.utc)
            stmt = stmt.where(or_(UserRole.expires_at.is_(None), UserRole.expires_at > now))
        return list(self.db.execute(stmt.order_by(UserRole.created_at.desc())).scalars().all())

    def find_matching(self, assignment: UserRole) -> UserRole | None:
        """An existing assignment with the same (user, role, scope key)."""
        stmt = select(UserRole).where(
            UserRole.user_id == assignment.user_id,
            UserRole.role_id == assignment.role_id,
            UserRole.scope == assignment.scope,
            UserRole.organization_id.is_(assignment.organization_id)
            if assignment.organization_id is None
            else UserRole.organization_id == assignment.organization_id,
            UserRole.department_id.is_(assignment.department_id)
            if assignment.department_id is None
            else UserRole.department_id == assignment.department_id,
            UserRole.team_id.is_(assignment.team_id)
            if assignment.team_id is None
            else UserRole.team_id == assignment.team_id,
            UserRole.project_id.is_(assignment.project_id)
            if assignment.project_id is None
            else UserRole.project_id == assignment.project_id,
            UserRole.resource_id.is_(assignment.resource_id)
            if assignment.resource_id is None
            else UserRole.resource_id == assignment.resource_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def add(self, assignment: UserRole) -> UserRole:
        self.db.add(assignment)
        self.db.flush()
        return assignment

    def delete(self, assignment: UserRole) -> None:
        self.db.delete(assignment)
        self.db.flush()


class RoleHierarchyRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, edge_id: uuid.UUID) -> RoleHierarchy | None:
        return self.db.get(RoleHierarchy, edge_id)

    def get_edge(self, parent_role_id: uuid.UUID, child_role_id: uuid.UUID) -> RoleHierarchy | None:
        return self.db.execute(
            select(RoleHierarchy).where(
                RoleHierarchy.parent_role_id == parent_role_id,
                RoleHierarchy.child_role_id == child_role_id,
            )
        ).scalar_one_or_none()

    def list(self) -> list[RoleHierarchy]:
        return list(self.db.execute(select(RoleHierarchy)).scalars().all())

    def children_of(self, role_id: uuid.UUID) -> list[uuid.UUID]:
        return [
            cid for (cid,) in self.db.execute(
                select(RoleHierarchy.child_role_id).where(RoleHierarchy.parent_role_id == role_id)
            )
        ]

    def add(self, edge: RoleHierarchy) -> RoleHierarchy:
        self.db.add(edge)
        self.db.flush()
        return edge

    def delete(self, edge: RoleHierarchy) -> None:
        self.db.delete(edge)
        self.db.flush()


class AuthorizationAuditRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, row: AuthorizationAudit) -> AuthorizationAudit:
        self.db.add(row)
        self.db.flush()
        return row

    def list(
        self,
        organization_id: uuid.UUID | None,
        *,
        event_type: str | None = None,
        identity_id: uuid.UUID | None = None,
        limit: int = 100,
    ) -> list[AuthorizationAudit]:
        stmt = select(AuthorizationAudit)
        if organization_id is not None:
            stmt = stmt.where(
                or_(
                    AuthorizationAudit.organization_id == organization_id,
                    AuthorizationAudit.organization_id.is_(None),
                )
            )
        if event_type:
            stmt = stmt.where(AuthorizationAudit.event_type == event_type)
        if identity_id:
            stmt = stmt.where(AuthorizationAudit.identity_id == identity_id)
        stmt = stmt.order_by(AuthorizationAudit.created_at.desc()).limit(min(max(limit, 1), 500))
        return list(self.db.execute(stmt).scalars().all())
