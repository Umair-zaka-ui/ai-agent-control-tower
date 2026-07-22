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
    # Account recovery (4.2.2.3.3 §18). Reading recovery/reset activity is a distinct
    # power from resetting a password, though both currently sit on the admin roles.
    "recovery.view": "View password-reset and recovery events in the organization",
    # Account protection (4.2.2.3.4 §20). One permission gates the whole security
    # console: locks, blocked IPs, protection rules and risk events.
    "security.protection": "View and manage account protection: locks, blocked IPs, rules",
    "rbac.manage": "Manage roles and role assignments",
    # Enterprise authorization platform (Phase 4.3.1 §20, §25). Split so viewing the
    # role/permission catalog is a lesser power than editing it or assigning roles.
    "role.view": "View roles, permissions, groups and role assignments",
    "role.manage": "Create, edit, archive and delete roles, permissions and hierarchy",
    "role.assign": "Assign and remove roles (including scoped assignments)",
    # Enterprise organization hierarchy (Phase 4.3.3 §15, §19).
    "organization.view": "View the organization hierarchy, ownership and delegations",
    "organization.manage": "Manage business units, departments, teams, projects, ownership and delegation",
    # Resource-based authorization (Phase 4.3.4 §16, §19). Owners manage their own
    # resources without either permission; these gate the org-wide admin surface.
    "resource.view": "View the resource registry, ACLs, shares, delegations and ownership history",
    "resource.manage": "Administer any resource: ACLs, shares, delegations, ownership transfer, policy",
    # ABAC engine (Phase 4.3.5 §37). Authoring and publishing are separable so
    # enterprises can enforce segregation of duties.
    "authorization.abac.view": "View ABAC policies, versions and the attribute catalog",
    "authorization.abac.create": "Create draft ABAC policies",
    "authorization.abac.update": "Edit draft ABAC policies (new version for published ones)",
    "authorization.abac.publish": "Validate and publish ABAC policies (incl. rollback)",
    "authorization.abac.disable": "Disable active ABAC policies",
    "authorization.abac.archive": "Archive ABAC policies",
    "authorization.abac.simulate": "Run the ABAC policy simulator",
    "authorization.abac.audit": "View ABAC evaluations and internal explanations",
    "authorization.attribute.manage": "Create and edit ABAC attribute definitions",
    "authorization.exception.manage": "Create and revoke ABAC policy exceptions",
    # Administration portal (Phase 4.3.7 §21). The portal surfaces existing
    # capabilities behind one control plane; these gate the /api/v1/admin API.
    "admin.dashboard.view": "View the authorization administration dashboard",
    "admin.roles.manage": "Manage roles and permission assignments from the admin portal",
    "admin.permissions.manage": "Manage the permission catalog from the admin portal",
    "admin.organizations.manage": "Manage the organization hierarchy from the admin portal",
    "admin.resources.manage": "Manage resource authorization from the admin portal",
    "admin.policies.manage": "Manage ABAC policies from the admin portal",
    "admin.simulator.use": "Run the admin policy simulator",
    "admin.audit.view": "View the authorization audit center",
    "admin.analytics.view": "View the security analytics dashboard",
    "admin.reviews.manage": "Create and run access review campaigns",
    # Identity Governance & Administration (Phase 4.3.8 §18).
    "governance.dashboard.view": "View the governance dashboard and KPIs",
    "governance.certification.manage": "Create, launch and decide access certification campaigns",
    "governance.sod.manage": "Create, approve and disable Separation-of-Duties rules",
    "governance.sod.view": "View SoD rules and findings",
    "governance.toxic.manage": "Create and disable toxic-permission rules",
    "governance.privileged.manage": "Review, approve and revoke privileged accounts",
    "governance.orphaned.manage": "Scan for and resolve orphaned identities",
    "governance.findings.manage": "View and triage governance findings",
    "governance.remediation.manage": "Create and execute remediation actions",
    "governance.compliance.view": "Generate and view compliance evidence reports",
    "governance.analytics.view": "View governance analytics and risk distribution",
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
    # Agent Runtime & Lifecycle Management (Phase 5.0 §67).
    "runtime.agent.view": "View runtime agents, definitions and versions",
    "runtime.agent.create": "Register new runtime agents and definitions",
    "runtime.agent.update": "Update runtime agent metadata and definitions",
    "runtime.agent.delete": "Delete runtime agents",
    "runtime.agent.validate": "Validate agents and agent versions",
    "runtime.agent.approve": "Approve agents for activation",
    "runtime.agent.activate": "Activate validated/approved agents",
    "runtime.agent.suspend": "Suspend agents",
    "runtime.agent.retire": "Archive or retire agents",
    "runtime.version.view": "View agent versions",
    "runtime.version.create": "Create draft agent versions",
    "runtime.version.update": "Edit draft agent versions",
    "runtime.version.publish": "Publish immutable agent versions",
    "runtime.version.deprecate": "Deprecate published agent versions",
    "runtime.version.revoke": "Revoke agent versions",
    "runtime.deployment.view": "View deployments and deployment health",
    "runtime.deployment.create": "Create deployments",
    "runtime.deployment.deploy": "Deploy, suspend, resume and retire deployments",
    "runtime.deployment.rollback": "Roll back a deployment to a previous version",
    "runtime.execution.view": "View executions, tool calls and telemetry",
    "runtime.execution.create": "Request agent executions",
    "runtime.execution.cancel": "Cancel queued or running executions",
    "runtime.execution.retry": "Retry or replay executions",
    "runtime.capability.manage": "Manage the capability registry and agent capability assignments",
    "runtime.tool.manage": "Manage the tool registry",
    "runtime.tool.assign": "Assign tools to agents with constraints",
    "runtime.health.view": "View runtime health, worker and heartbeat status",
    "runtime.telemetry.view": "View runtime telemetry and execution traces",
    "runtime.cost.view": "View runtime cost and token usage",
    "runtime.approval.review": "Approve or reject runtime approval requests",
    "runtime.kill_switch.execute": "Activate the runtime kill switch at any scope",
    # Enterprise Agent Registry (Phase 5.1 §57).
    "runtime.agent.register": "Move a draft agent into the REGISTERED lifecycle state",
    "runtime.agent.submit": "Submit a validated agent for approval",
    "runtime.agent.reject": "Reject an agent's registration",
    "runtime.agent.resume": "Resume a suspended agent",
    "runtime.agent.deprecate": "Deprecate an active or suspended agent",
    "runtime.agent.archive": "Archive an agent",
    "runtime.agent.restore": "Restore an archived agent back to draft",
    "runtime.agent.identity.associate": "Associate an existing eligible machine identity with an agent",
    "runtime.agent.identity.create": "Create and associate a new machine identity for an agent",
    "runtime.agent.identity.replace": "Replace an agent's machine identity",
    "runtime.agent.ownership.view": "View agent ownership and ownership history",
    "runtime.agent.ownership.transfer": "Transfer agent ownership roles",
    "runtime.agent.validation.view": "View agent validation runs and reports",
    "runtime.agent.duplicate.review": "Review and decide on detected duplicate agents",
    "runtime.agent.import": "Bulk-import agent registrations",
    "runtime.agent.export": "Export agent registrations",
    "runtime.agent.audit.view": "View agent registry audit and lifecycle history",
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
