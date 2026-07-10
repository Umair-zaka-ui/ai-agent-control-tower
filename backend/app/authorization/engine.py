"""The Enterprise Permission Engine (Phase 4.3.2).

Every authorization decision in the platform flows through ``PermissionEngine``.
It resolves an identity's roles (with inheritance), collects their permission
grants (allow/deny), expands wildcards, applies scope, resolves conflicts
(explicit deny wins), and returns a structured decision — default deny.

The engine is deliberately *pure* over a resolved **grant list**: resolution
(the DB-heavy part) is done once and cached (``app.authorization.cache``); the
evaluation below is in-memory and fast.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization.enums import AssignmentScope, AuthorizationDecision as Decision
from app.models.rbac import Role, RoleHierarchy, RolePermission, UserRole
from app.models.user import User
from app.services.rbac_service import SYSTEM_ROLE_PERMISSIONS

ALLOW = "ALLOW"
DENY = "DENY"
GLOBAL_WILDCARD = "*"


# --------------------------------------------------------------------------- #
# Value objects
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Grant:
    """One resolved permission grant: a pattern (concrete code or wildcard), its
    effect, the scope it applies at, and the role it came from."""

    pattern: str
    effect: str  # ALLOW | DENY
    scope: str  # AssignmentScope value
    source_role: str
    organization_id: str | None = None
    department_id: str | None = None
    team_id: str | None = None
    project_id: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None

    def to_json(self) -> dict:
        return {
            "pattern": self.pattern, "effect": self.effect, "scope": self.scope,
            "source_role": self.source_role, "organization_id": self.organization_id,
            "department_id": self.department_id, "team_id": self.team_id,
            "project_id": self.project_id, "resource_type": self.resource_type,
            "resource_id": self.resource_id,
        }

    @classmethod
    def from_json(cls, d: dict) -> "Grant":
        return cls(**d)


@dataclass(frozen=True)
class ResourceContext:
    """What is being acted upon. All optional — a permission-only check (endpoint
    gating) passes at most an organization."""

    organization_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None


@dataclass
class AuthorizationResult:
    allowed: bool
    permission: str
    reason: str
    scope: str | None = None
    source_role: str | None = None
    evaluation_time_ms: float | None = None
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "permission": self.permission,
            "reason": self.reason,
            "scope": self.scope,
            "source_role": self.source_role,
        }


# --------------------------------------------------------------------------- #
# Wildcard resolver (§13, §14)
# --------------------------------------------------------------------------- #
class WildcardResolver:
    @staticmethod
    def matches(pattern: str, code: str) -> bool:
        """Does a granted ``pattern`` cover the requested ``code``?

        ``*`` matches everything; ``resource.*`` matches any action on that
        resource; otherwise an exact match.
        """
        if pattern == GLOBAL_WILDCARD:
            return True
        if pattern == code:
            return True
        if pattern.endswith(".*"):
            return code.split(".", 1)[0] == pattern[:-2]
        return False

    @staticmethod
    def expand(pattern: str, known_codes: set[str]) -> set[str]:
        """Expand a wildcard against the known catalog (used for display/introspection)."""
        if pattern == GLOBAL_WILDCARD:
            return set(known_codes)
        if pattern.endswith(".*"):
            resource = pattern[:-2]
            return {c for c in known_codes if c.split(".", 1)[0] == resource}
        return {pattern} if pattern in known_codes else set()


# --------------------------------------------------------------------------- #
# Role resolver (§12)
# --------------------------------------------------------------------------- #
class RoleResolver:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._children: dict[uuid.UUID, list[uuid.UUID]] | None = None

    def _hierarchy(self) -> dict[uuid.UUID, list[uuid.UUID]]:
        if self._children is None:
            self._children = {}
            for parent, child in self.db.execute(
                select(RoleHierarchy.parent_role_id, RoleHierarchy.child_role_id)
            ):
                self._children.setdefault(parent, []).append(child)
        return self._children

    def descendants(self, role_id: uuid.UUID) -> set[uuid.UUID]:
        """Every role reachable from ``role_id`` via parent->child edges (inherited)."""
        children = self._hierarchy()
        seen: set[uuid.UUID] = set()
        stack = list(children.get(role_id, []))
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(children.get(node, []))
        return seen

    def resolve_with_inheritance(self, role_id: uuid.UUID) -> set[uuid.UUID]:
        return {role_id} | self.descendants(role_id)


# --------------------------------------------------------------------------- #
# Scope resolver (§15)
# --------------------------------------------------------------------------- #
class ScopeResolver:
    @staticmethod
    def applies(grant: Grant, user: User, ctx: ResourceContext | None) -> bool:
        scope = grant.scope
        user_org = str(user.organization_id) if user.organization_id else None

        if scope == AssignmentScope.GLOBAL.value:
            return True

        if scope == AssignmentScope.ORGANIZATION.value:
            target_org = str(ctx.organization_id) if (ctx and ctx.organization_id) else user_org
            return grant.organization_id in (None, target_org)

        # Narrower scopes only apply when the request names a matching target.
        if ctx is None:
            return False
        if scope == AssignmentScope.DEPARTMENT.value:
            return grant.department_id is not None and grant.department_id == (
                str(ctx.department_id) if ctx.department_id else None
            )
        if scope == AssignmentScope.TEAM.value:
            return grant.team_id is not None and grant.team_id == (
                str(ctx.team_id) if ctx.team_id else None
            )
        if scope == AssignmentScope.PROJECT.value:
            return grant.project_id is not None and grant.project_id == (
                str(ctx.project_id) if ctx.project_id else None
            )
        if scope == AssignmentScope.RESOURCE.value:
            return (
                grant.resource_type is not None
                and grant.resource_type == ctx.resource_type
                and grant.resource_id is not None
                and grant.resource_id == (str(ctx.resource_id) if ctx.resource_id else None)
            )
        return False


# --------------------------------------------------------------------------- #
# Conflict resolver (§16)
# --------------------------------------------------------------------------- #
class ConflictResolver:
    """Given the grants that *apply* and *match* the requested code, pick the
    decision. Order: explicit deny > allow > default deny."""

    @staticmethod
    def resolve(permission: str, matching: list[Grant]) -> AuthorizationResult:
        denies = [g for g in matching if g.effect == DENY]
        if denies:
            g = denies[0]
            return AuthorizationResult(
                allowed=False, permission=permission,
                reason=f"Explicitly denied by {g.source_role}", scope=g.scope,
                source_role=g.source_role,
            )
        allows = [g for g in matching if g.effect == ALLOW]
        if allows:
            # Prefer an exact (non-wildcard) grant for a clearer reason.
            exact = next((g for g in allows if g.pattern == permission), None)
            g = exact or allows[0]
            return AuthorizationResult(
                allowed=True, permission=permission,
                reason=f"Granted by {g.source_role}", scope=g.scope, source_role=g.source_role,
            )
        return AuthorizationResult(
            allowed=False, permission=permission, reason="Permission not assigned",
        )


# --------------------------------------------------------------------------- #
# Permission resolver (§11) — builds the full grant list for an identity
# --------------------------------------------------------------------------- #
class PermissionResolver:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.roles = RoleResolver(db)

    def resolve_grants(self, user: User) -> list[Grant]:
        grants: list[Grant] = []

        # 1. Legacy fallback: the four built-in roles keyed by ``User.role`` enum,
        #    treated as GLOBAL allows so pre-4.3 users keep exactly their access.
        for code in SYSTEM_ROLE_PERMISSIONS.get(user.role.value, set()):
            grants.append(Grant(pattern=code, effect=ALLOW, scope=AssignmentScope.GLOBAL.value,
                                source_role=f"legacy:{user.role.value}"))

        # 2. Explicit role assignments (scoped), each expanded through the hierarchy.
        now = datetime.now(timezone.utc)
        assignments = self.db.execute(
            select(UserRole).where(UserRole.user_id == user.id)
        ).scalars().all()
        for a in assignments:
            if a.expires_at is not None and a.expires_at <= now:
                continue  # lapsed assignment
            role_ids = self.roles.resolve_with_inheritance(a.role_id)
            for rid in role_ids:
                role = self.db.get(Role, rid)
                if role is None or role.status == "DELETED":
                    continue
                for rp in self.db.execute(
                    select(RolePermission).where(RolePermission.role_id == rid)
                ).scalars():
                    code = self._perm_code(rp.permission_id)
                    if code is None:
                        continue
                    grants.append(Grant(
                        pattern=code, effect=(rp.effect or ALLOW),
                        scope=a.scope, source_role=role.name,
                        organization_id=str(a.organization_id) if a.organization_id else None,
                        department_id=str(a.department_id) if a.department_id else None,
                        team_id=str(a.team_id) if a.team_id else None,
                        project_id=str(a.project_id) if a.project_id else None,
                        resource_type=a.resource_type,
                        resource_id=str(a.resource_id) if a.resource_id else None,
                    ))
        return grants

    def _perm_code(self, permission_id: uuid.UUID) -> str | None:
        from app.models.rbac import RbacPermission

        perm = self.db.get(RbacPermission, permission_id)
        return perm.code if perm else None


# --------------------------------------------------------------------------- #
# The engine (§19, §20)
# --------------------------------------------------------------------------- #
class PermissionEngine:
    """Coordinates the resolvers. Prefer the cached ``authorize`` entry points on
    ``app.authorization.cache.PermissionCacheService`` in the hot path; this class
    evaluates a decision given (or resolving) an identity's grants."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.resolver = PermissionResolver(db)

    def resolve_grants(self, user: User) -> list[Grant]:
        return self.resolver.resolve_grants(user)

    def evaluate(
        self,
        user: User,
        permission: str,
        grants: list[Grant],
        ctx: ResourceContext | None = None,
    ) -> AuthorizationResult:
        """Pure evaluation of a decision from a resolved grant list."""
        applicable = [
            g for g in grants
            if WildcardResolver.matches(g.pattern, permission) and ScopeResolver.applies(g, user, ctx)
        ]
        result = ConflictResolver.resolve(permission, applicable)
        if ctx is not None:
            result.resource_type = ctx.resource_type
            result.resource_id = ctx.resource_id
        return result

    def authorize(
        self, user: User, permission: str, ctx: ResourceContext | None = None
    ) -> AuthorizationResult:
        """Resolve grants (uncached) and evaluate. The cached path lives in
        ``PermissionCacheService.authorize``."""
        grants = self.resolve_grants(user)
        return self.evaluate(user, permission, grants, ctx)
