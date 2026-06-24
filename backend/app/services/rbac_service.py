"""Advanced RBAC service.

Provides the permission catalog, the built-in role -> permission mapping, a
seeding routine, and the runtime permission check used by route dependencies.

Backward compatibility: even if a user has no explicit ``user_roles`` rows, the
check falls back to permissions derived from their legacy ``User.role`` enum, so
Phase 1 users keep working without migration.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import UserRole
from app.models.organization import Organization
from app.models.rbac import RbacPermission, Role, RolePermission, UserRole as UserRoleLink
from app.models.user import User

# --- Permission catalog ---------------------------------------------------- #
PERMISSION_CATALOG: dict[str, str] = {
    "agent.create": "Register new agents",
    "agent.view": "View agents",
    "agent.update": "Update agents / change status",
    "agent.delete": "Delete agents",
    "apikey.create": "Issue agent API keys",
    "apikey.revoke": "Revoke agent API keys",
    "policy.create": "Create policies",
    "policy.view": "View policies",
    "policy.edit": "Edit policies",
    "policy.delete": "Delete policies",
    "permission.manage": "Manage agent permissions",
    "user.create": "Create users",
    "user.view": "View users",
    "rbac.manage": "Manage roles and role assignments",
    "approval.review": "Approve or reject pending actions",
    "audit.view": "View audit logs",
    "dashboard.view": "View dashboard metrics",
    "agent_action.create": "Submit agent actions",
    "agent_action.view": "View agent actions",
}

_ALL = set(PERMISSION_CATALOG)
_READ_ONLY = {"agent.view", "policy.view", "audit.view", "dashboard.view", "agent_action.view"}

# Built-in role -> permission codes.
SYSTEM_ROLE_PERMISSIONS: dict[str, set[str]] = {
    UserRole.SUPER_ADMIN.value: set(_ALL),
    UserRole.ADMIN.value: _ALL - {"rbac.manage"},
    UserRole.REVIEWER.value: _READ_ONLY | {"approval.review", "agent_action.create"},
    UserRole.VIEWER.value: set(_READ_ONLY),
}


def seed_rbac(db: Session, organization: Organization) -> None:
    """Ensure the permission catalog and built-in roles exist for an org, and
    assign each user a role matching their legacy ``User.role`` enum."""
    # 1. Permission catalog (global rows).
    existing_codes = {
        c for (c,) in db.execute(select(RbacPermission.code)).all()
    }
    code_to_perm: dict[str, RbacPermission] = {}
    for code, description in PERMISSION_CATALOG.items():
        if code in existing_codes:
            code_to_perm[code] = db.execute(
                select(RbacPermission).where(RbacPermission.code == code)
            ).scalar_one()
        else:
            perm = RbacPermission(code=code, description=description)
            db.add(perm)
            db.flush()
            code_to_perm[code] = perm

    # 2. System roles for this organization + their permission grants.
    for role_name, perm_codes in SYSTEM_ROLE_PERMISSIONS.items():
        role = db.execute(
            select(Role).where(
                Role.organization_id == organization.id, Role.name == role_name
            )
        ).scalar_one_or_none()
        if role is None:
            role = Role(
                organization_id=organization.id,
                name=role_name,
                description=f"Built-in {role_name} role",
                is_system=True,
            )
            db.add(role)
            db.flush()

        granted = {
            pid for (pid,) in db.execute(
                select(RolePermission.permission_id).where(RolePermission.role_id == role.id)
            ).all()
        }
        for code in perm_codes:
            perm = code_to_perm[code]
            if perm.id not in granted:
                db.add(RolePermission(role_id=role.id, permission_id=perm.id))

    db.flush()

    # 3. Map each user to the role matching their legacy enum (idempotent).
    users = db.execute(
        select(User).where(User.organization_id == organization.id)
    ).scalars().all()
    for user in users:
        role = db.execute(
            select(Role).where(
                Role.organization_id == organization.id, Role.name == user.role.value
            )
        ).scalar_one_or_none()
        if role is None:
            continue
        link = db.execute(
            select(UserRoleLink).where(
                UserRoleLink.user_id == user.id, UserRoleLink.role_id == role.id
            )
        ).scalar_one_or_none()
        if link is None:
            db.add(UserRoleLink(user_id=user.id, role_id=role.id))
    db.flush()


def get_user_permissions(db: Session, user: User) -> set[str]:
    """All permission codes a user holds (explicit roles + legacy-role fallback)."""
    codes: set[str] = set()

    rows = db.execute(
        select(RbacPermission.code)
        .join(RolePermission, RolePermission.permission_id == RbacPermission.id)
        .join(UserRoleLink, UserRoleLink.role_id == RolePermission.role_id)
        .where(UserRoleLink.user_id == user.id)
    ).all()
    codes.update(c for (c,) in rows)

    # Fallback: derive from the legacy enum so un-seeded users still work.
    codes.update(SYSTEM_ROLE_PERMISSIONS.get(user.role.value, set()))
    return codes


def user_has_permission(db: Session, user: User, code: str) -> bool:
    return code in get_user_permissions(db, user)
