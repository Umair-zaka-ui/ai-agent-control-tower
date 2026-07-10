"""Authorization services (Phase 4.3.1 §18).

Business rules for roles, permissions, groups, scoped assignments and the acyclic
role hierarchy — each recording its change through ``AuthorizationAuditService``.
"""

from __future__ import annotations

import re
import uuid
from collections import deque
from datetime import datetime

from sqlalchemy.orm import Session

from app.authorization.enums import (
    AssignmentScope,
    AuthorizationAuditEvent,
    AuthorizationDecision,
    RoleCategory,
    RoleStatus,
)
from app.authorization.repositories import (
    AuthorizationAuditRepository,
    PermissionGroupRepository,
    PermissionRepository,
    RoleAssignmentRepository,
    RoleHierarchyRepository,
    RoleRepository,
)
from app.identity.errors import ErrorCode, IdentityError
from app.models.rbac import (
    AuthorizationAudit,
    RbacPermission,
    Role,
    RoleHierarchy,
    UserRole,
)

# §11 — resource.action, lowercase, no spaces. Action may be "*" (wildcard, 4.3.2).
_PERMISSION_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9_*]+$")


# --------------------------------------------------------------------------- #
# Audit (§18 AuthorizationAuditService, §23)
# --------------------------------------------------------------------------- #
class AuthorizationAuditService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = AuthorizationAuditRepository(db)

    def record_change(
        self,
        event: AuthorizationAuditEvent,
        *,
        organization_id: uuid.UUID | None,
        actor_id: uuid.UUID | None,
        identity_id: uuid.UUID | None = None,
        permission: str | None = None,
        meta: dict | None = None,
    ) -> AuthorizationAudit:
        return self.repo.add(
            AuthorizationAudit(
                organization_id=organization_id,
                actor_id=actor_id,
                identity_id=identity_id,
                event_type=event.value,
                permission=permission,
                meta=meta,
            )
        )

    def record_decision(
        self,
        *,
        organization_id: uuid.UUID | None,
        identity_id: uuid.UUID | None,
        permission: str,
        decision: AuthorizationDecision,
        reason: str,
        resource_type: str | None = None,
        resource_id: uuid.UUID | None = None,
    ) -> AuthorizationAudit:
        return self.repo.add(
            AuthorizationAudit(
                organization_id=organization_id,
                identity_id=identity_id,
                event_type=AuthorizationAuditEvent.AUTHORIZATION_DECISION.value,
                permission=permission,
                resource_type=resource_type,
                resource_id=resource_id,
                decision=decision.value,
                reason=reason,
            )
        )


# --------------------------------------------------------------------------- #
# Permissions (§18 PermissionService)
# --------------------------------------------------------------------------- #
class PermissionService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = PermissionRepository(db)
        self.audit = AuthorizationAuditService(db)

    @staticmethod
    def validate_name(code: str) -> None:
        if not _PERMISSION_NAME_RE.match(code or ""):
            raise IdentityError(
                ErrorCode.INVALID_PERMISSION_NAME,
                "Permission names must be lowercase 'resource.action' with no spaces.",
            )

    def create(
        self,
        *,
        code: str,
        description: str | None,
        display_name: str | None,
        group_id: uuid.UUID | None,
        actor_id: uuid.UUID | None,
        organization_id: uuid.UUID | None,
    ) -> RbacPermission:
        self.validate_name(code)
        if self.repo.get_by_code(code) is not None:
            raise IdentityError(ErrorCode.PERMISSION_ALREADY_EXISTS, "Permission already exists.")
        resource, _, action = code.partition(".")
        perm = self.repo.add(
            RbacPermission(
                code=code,
                description=description,
                display_name=display_name or code,
                group_id=group_id,
                resource_type=resource,
                action=action or "*",
                is_system=False,
            )
        )
        self.audit.record_change(
            AuthorizationAuditEvent.PERMISSION_CREATED,
            organization_id=organization_id, actor_id=actor_id,
            permission=code, meta={"permission_id": str(perm.id)},
        )
        return perm

    def update(
        self,
        permission_id: uuid.UUID,
        *,
        description: str | None,
        display_name: str | None,
        group_id: uuid.UUID | None,
        actor_id: uuid.UUID | None,
        organization_id: uuid.UUID | None,
    ) -> RbacPermission:
        perm = self.repo.get(permission_id)
        if perm is None:
            raise IdentityError(ErrorCode.PERMISSION_NOT_FOUND, "Permission not found.")
        if description is not None:
            perm.description = description
        if display_name is not None:
            perm.display_name = display_name
        if group_id is not None:
            perm.group_id = group_id
        self.db.flush()
        self.audit.record_change(
            AuthorizationAuditEvent.PERMISSION_UPDATED,
            organization_id=organization_id, actor_id=actor_id, permission=perm.code,
        )
        return perm

    def delete(
        self, permission_id: uuid.UUID, *, actor_id: uuid.UUID | None, organization_id: uuid.UUID | None
    ) -> None:
        perm = self.repo.get(permission_id)
        if perm is None:
            raise IdentityError(ErrorCode.PERMISSION_NOT_FOUND, "Permission not found.")
        if perm.is_system:
            raise IdentityError(
                ErrorCode.SYSTEM_ROLE_PROTECTED, "System permissions cannot be deleted."
            )
        code = perm.code
        self.db.delete(perm)
        self.db.flush()
        self.audit.record_change(
            AuthorizationAuditEvent.PERMISSION_DELETED,
            organization_id=organization_id, actor_id=actor_id, permission=code,
        )


# --------------------------------------------------------------------------- #
# Permission groups (§18)
# --------------------------------------------------------------------------- #
class PermissionGroupService:
    def __init__(self, db: Session) -> None:
        self.repo = PermissionGroupRepository(db)

    def list(self):
        return self.repo.list()


# --------------------------------------------------------------------------- #
# Roles (§18 RoleService)
# --------------------------------------------------------------------------- #
class RoleService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = RoleRepository(db)
        self.perms = PermissionRepository(db)
        self.audit = AuthorizationAuditService(db)

    def get_or_404(self, role_id: uuid.UUID, organization_id: uuid.UUID | None) -> Role:
        role = self.repo.get_visible(role_id, organization_id)
        if role is None or role.status == RoleStatus.DELETED.value:
            raise IdentityError(ErrorCode.ROLE_NOT_FOUND, "Role not found.")
        return role

    def create(
        self,
        *,
        name: str,
        display_name: str | None,
        description: str | None,
        category: str,
        priority: int,
        permission_codes: list[str],
        organization_id: uuid.UUID,
        actor_id: uuid.UUID | None,
    ) -> Role:
        if not name or not name.strip():
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "Role name is required.")
        if category not in {c.value for c in RoleCategory}:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "Unknown role category.")
        if self.repo.get_by_name(organization_id, name) is not None:
            raise IdentityError(ErrorCode.ROLE_ALREADY_EXISTS, "A role with that name already exists.")
        role = self.repo.add(
            Role(
                organization_id=organization_id,
                name=name.strip(),
                display_name=display_name or name.strip(),
                description=description,
                category=category,
                status=RoleStatus.ACTIVE.value,
                is_system=False,
                is_assignable=True,
                priority=priority,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        self._set_permissions(role, permission_codes, actor_id, organization_id, audit=False)
        self.audit.record_change(
            AuthorizationAuditEvent.ROLE_CREATED,
            organization_id=organization_id, actor_id=actor_id,
            meta={"role_id": str(role.id), "name": role.name},
        )
        return role

    def update(
        self,
        role: Role,
        *,
        display_name: str | None,
        description: str | None,
        priority: int | None,
        status: str | None,
        permission_codes: list[str] | None,
        actor_id: uuid.UUID | None,
        organization_id: uuid.UUID | None,
    ) -> Role:
        # System roles are catalog fixtures: their permission set and name are
        # protected, though display metadata may be curated.
        if role.is_system and permission_codes is not None:
            raise IdentityError(
                ErrorCode.SYSTEM_ROLE_PROTECTED, "A system role's permissions cannot be changed."
            )
        if display_name is not None:
            role.display_name = display_name
        if description is not None:
            role.description = description
        if priority is not None:
            role.priority = priority
        if status is not None:
            if status not in {s.value for s in RoleStatus}:
                raise IdentityError(ErrorCode.VALIDATION_ERROR, "Unknown role status.")
            if role.is_system and status in (RoleStatus.ARCHIVED.value, RoleStatus.DELETED.value):
                raise IdentityError(
                    ErrorCode.SYSTEM_ROLE_PROTECTED, "System roles cannot be archived or deleted."
                )
            role.status = status
            role.is_assignable = RoleStatus(status).is_assignable_state
        if permission_codes is not None:
            self._set_permissions(role, permission_codes, actor_id, organization_id, audit=True)
        role.updated_by = actor_id
        self.db.flush()
        self.audit.record_change(
            AuthorizationAuditEvent.ROLE_UPDATED,
            organization_id=organization_id, actor_id=actor_id,
            meta={"role_id": str(role.id)},
        )
        return role

    def archive(self, role: Role, *, actor_id: uuid.UUID | None, organization_id: uuid.UUID | None) -> Role:
        if role.is_system:
            raise IdentityError(ErrorCode.SYSTEM_ROLE_PROTECTED, "System roles cannot be archived.")
        role.status = RoleStatus.ARCHIVED.value
        role.is_assignable = False
        role.updated_by = actor_id
        self.db.flush()
        self.audit.record_change(
            AuthorizationAuditEvent.ROLE_ARCHIVED,
            organization_id=organization_id, actor_id=actor_id, meta={"role_id": str(role.id)},
        )
        return role

    def delete(self, role: Role, *, actor_id: uuid.UUID | None, organization_id: uuid.UUID | None) -> None:
        if role.is_system:
            raise IdentityError(ErrorCode.SYSTEM_ROLE_PROTECTED, "System roles cannot be deleted.")
        if self.repo.assignment_count(role.id) > 0:
            raise IdentityError(
                ErrorCode.ROLE_HAS_ASSIGNMENTS,
                "This role is still assigned to one or more identities.",
            )
        role_id, name = role.id, role.name
        self.db.delete(role)  # cascades role_permissions + role_hierarchy edges
        self.db.flush()
        self.audit.record_change(
            AuthorizationAuditEvent.ROLE_DELETED,
            organization_id=organization_id, actor_id=actor_id,
            meta={"role_id": str(role_id), "name": name},
        )

    def _set_permissions(
        self,
        role: Role,
        codes: list[str],
        actor_id: uuid.UUID | None,
        organization_id: uuid.UUID | None,
        *,
        audit: bool,
    ) -> None:
        wanted: set[str] = set()
        for code in codes:
            perm = self.perms.get_by_code(code)
            if perm is None:
                raise IdentityError(ErrorCode.PERMISSION_NOT_FOUND, f"Unknown permission: {code}")
            wanted.add(code)
        current = {p.code: p for p in role.permissions}
        # Grant new.
        for code in wanted - set(current):
            role.permissions.append(self.perms.get_by_code(code))
            if audit:
                self.audit.record_change(
                    AuthorizationAuditEvent.PERMISSION_ASSIGNED,
                    organization_id=organization_id, actor_id=actor_id, permission=code,
                    meta={"role_id": str(role.id)},
                )
        # Revoke removed.
        for code in set(current) - wanted:
            role.permissions.remove(current[code])
            if audit:
                self.audit.record_change(
                    AuthorizationAuditEvent.PERMISSION_REMOVED,
                    organization_id=organization_id, actor_id=actor_id, permission=code,
                    meta={"role_id": str(role.id)},
                )
        self.db.flush()


# --------------------------------------------------------------------------- #
# Role hierarchy (§17, §18 RoleHierarchyService)
# --------------------------------------------------------------------------- #
class RoleHierarchyService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = RoleHierarchyRepository(db)
        self.roles = RoleRepository(db)
        self.audit = AuthorizationAuditService(db)

    def _reachable_children(self, start: uuid.UUID) -> set[uuid.UUID]:
        """All roles reachable from ``start`` following parent->child edges."""
        seen: set[uuid.UUID] = set()
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for child in self.repo.children_of(node):
                if child not in seen:
                    seen.add(child)
                    queue.append(child)
        return seen

    def would_create_cycle(self, parent_id: uuid.UUID, child_id: uuid.UUID) -> bool:
        # A self-edge is trivially a cycle; otherwise a cycle forms iff the parent
        # is already reachable from the child.
        if parent_id == child_id:
            return True
        return parent_id in self._reachable_children(child_id)

    def add_edge(
        self,
        parent_id: uuid.UUID,
        child_id: uuid.UUID,
        *,
        organization_id: uuid.UUID | None,
        actor_id: uuid.UUID | None,
    ) -> RoleHierarchy:
        if self.roles.get(parent_id) is None or self.roles.get(child_id) is None:
            raise IdentityError(ErrorCode.ROLE_NOT_FOUND, "Role not found.")
        if self.would_create_cycle(parent_id, child_id):
            raise IdentityError(
                ErrorCode.CIRCULAR_ROLE_HIERARCHY,
                "That edge would create a circular role hierarchy.",
            )
        existing = self.repo.get_edge(parent_id, child_id)
        if existing is not None:
            return existing
        edge = self.repo.add(RoleHierarchy(parent_role_id=parent_id, child_role_id=child_id))
        self.audit.record_change(
            AuthorizationAuditEvent.ROLE_HIERARCHY_UPDATED,
            organization_id=organization_id, actor_id=actor_id,
            meta={"parent_role_id": str(parent_id), "child_role_id": str(child_id)},
        )
        return edge

    def remove_edge(
        self, edge_id: uuid.UUID, *, organization_id: uuid.UUID | None, actor_id: uuid.UUID | None
    ) -> None:
        edge = self.repo.get(edge_id)
        if edge is None:
            raise IdentityError(ErrorCode.ROLE_HIERARCHY_EDGE_NOT_FOUND, "Hierarchy edge not found.")
        meta = {"parent_role_id": str(edge.parent_role_id), "child_role_id": str(edge.child_role_id)}
        self.repo.delete(edge)
        self.audit.record_change(
            AuthorizationAuditEvent.ROLE_HIERARCHY_REMOVED,
            organization_id=organization_id, actor_id=actor_id, meta=meta,
        )

    def resolve_effective_permissions(self, role_id: uuid.UUID) -> set[str]:
        """A role's own permissions ∪ the permissions of every descendant role (§17)."""
        codes: set[str] = set()
        for rid in {role_id} | self._reachable_children(role_id):
            role = self.roles.get(rid)
            if role is not None:
                codes.update(p.code for p in role.permissions)
        return codes


# --------------------------------------------------------------------------- #
# Role assignment (§14, §15, §18 RoleAssignmentService)
# --------------------------------------------------------------------------- #
_SCOPE_REQUIRES = {
    AssignmentScope.DEPARTMENT: "department_id",
    AssignmentScope.TEAM: "team_id",
    AssignmentScope.PROJECT: "project_id",
}


class RoleAssignmentService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = RoleAssignmentRepository(db)
        self.roles = RoleRepository(db)
        self.audit = AuthorizationAuditService(db)

    def assign(
        self,
        *,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
        scope: str,
        organization_id: uuid.UUID,
        department_id: uuid.UUID | None = None,
        team_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        resource_type: str | None = None,
        resource_id: uuid.UUID | None = None,
        expires_at: datetime | None = None,
        actor_id: uuid.UUID | None,
    ) -> UserRole:
        try:
            scope_enum = AssignmentScope(scope)
        except ValueError as exc:
            raise IdentityError(ErrorCode.INVALID_SCOPE, "Unknown assignment scope.") from exc

        role = self.roles.get_visible(role_id, organization_id)
        if role is None or role.status == RoleStatus.DELETED.value:
            raise IdentityError(ErrorCode.ROLE_NOT_FOUND, "Role not found.")
        if not role.is_assignable:
            raise IdentityError(ErrorCode.INVALID_SCOPE, "This role is not assignable.")

        # Scope/target consistency (§15).
        required = _SCOPE_REQUIRES.get(scope_enum)
        locals_map = {"department_id": department_id, "team_id": team_id, "project_id": project_id}
        if required and locals_map[required] is None:
            raise IdentityError(
                ErrorCode.INVALID_SCOPE, f"{scope_enum.value} scope requires a {required}."
            )
        if scope_enum is AssignmentScope.RESOURCE and (resource_type is None or resource_id is None):
            raise IdentityError(
                ErrorCode.INVALID_SCOPE, "RESOURCE scope requires resource_type and resource_id."
            )
        # ORGANIZATION scope defaults to the acting org.
        org_for_row = organization_id if scope_enum in (
            AssignmentScope.ORGANIZATION, AssignmentScope.DEPARTMENT,
            AssignmentScope.TEAM, AssignmentScope.PROJECT, AssignmentScope.RESOURCE,
        ) else None

        candidate = UserRole(
            user_id=user_id, role_id=role_id, scope=scope_enum.value,
            organization_id=org_for_row, department_id=department_id, team_id=team_id,
            project_id=project_id, resource_type=resource_type, resource_id=resource_id,
            expires_at=expires_at, assigned_by=actor_id,
        )
        existing = self.repo.find_matching(candidate)
        if existing is not None:
            existing.expires_at = expires_at
            existing.assigned_by = actor_id
            self.db.flush()
            return existing

        assignment = self.repo.add(candidate)
        self.audit.record_change(
            AuthorizationAuditEvent.ROLE_ASSIGNED,
            organization_id=organization_id, actor_id=actor_id, identity_id=user_id,
            meta={"assignment_id": str(assignment.id), "role_id": str(role_id),
                  "scope": scope_enum.value},
        )
        return assignment

    def remove(
        self, assignment_id: uuid.UUID, *, organization_id: uuid.UUID | None, actor_id: uuid.UUID | None
    ) -> None:
        assignment = self.repo.get(assignment_id)
        if assignment is None:
            raise IdentityError(ErrorCode.ROLE_ASSIGNMENT_NOT_FOUND, "Role assignment not found.")
        meta = {"assignment_id": str(assignment.id), "role_id": str(assignment.role_id)}
        user_id = assignment.user_id
        self.repo.delete(assignment)
        self.audit.record_change(
            AuthorizationAuditEvent.ROLE_REMOVED,
            organization_id=organization_id, actor_id=actor_id, identity_id=user_id, meta=meta,
        )
