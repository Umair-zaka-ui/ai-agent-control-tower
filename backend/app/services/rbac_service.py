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
    # Administrative session management (SRS 4.2.2.2 §17, §32). Kept separate from
    # user.view: reading who is signed in where is a lesser power than forcibly
    # ending someone's session, and the two are granted to different roles.
    "session.view": "View any user's sessions and devices in the organization",
    "session.revoke": "Force-logout another user's sessions (admin force-logout)",
    # Enterprise onboarding (4.2.2.3.1 §15). Viewing who has been invited is a
    # lesser power than being able to invite -- an invitation is an offer of access.
    "invitation.view": "View pending invitations in the organization",
    "invitation.manage": "Create, resend and cancel invitations",
    # Credential management (4.2.2.3.2 §16, §17). Resetting another user's password
    # is a higher power than reading the org's credential posture, so they are two
    # permissions even though both currently sit on the same admin roles.
    "credential.reset": "Reset another user's password and issue temporary credentials",
    "credential.dashboard": "View the organization password/credential dashboard",
    "rbac.manage": "Manage roles and role assignments",
    "approval.view": "View the approval queue and review details",
    "approval.review": "Approve or reject pending actions",
    "approval.escalate": "Escalate approvals to another reviewer or team",
    "approval.assign": "Assign or reassign approval reviewers",
    "audit.view": "View audit logs",
    "audit.export": "Export audit logs; view security & compliance dashboards and raw payloads",
    "dashboard.view": "View dashboard metrics",
    "agent_action.create": "Submit agent actions",
    "agent_action.view": "View agent actions",
    "analytics.view": "View analytics dashboards (risk, performance, policy, cost, reports)",
    "analytics.executive": "View the executive analytics dashboard",
    "analytics.operations": "View the operations analytics dashboard",
}

_ALL = set(PERMISSION_CATALOG)
_READ_ONLY = {
    "agent.view",
    "policy.view",
    "audit.view",
    "dashboard.view",
    "agent_action.view",
    "approval.view",
}

# Built-in role -> permission codes.
SYSTEM_ROLE_PERMISSIONS: dict[str, set[str]] = {
    UserRole.SUPER_ADMIN.value: set(_ALL),
    UserRole.ADMIN.value: _ALL - {"rbac.manage"},
    UserRole.REVIEWER.value: _READ_ONLY
    | {
        "approval.review",
        "approval.escalate",
        "approval.assign",
        "agent_action.create",
        # Reviewers see general analytics + operations, but not executive.
        "analytics.view",
        "analytics.operations",
    },
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
