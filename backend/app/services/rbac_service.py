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
    "runtime.version.retire": "Retire deprecated agent versions",
    "runtime.signing.view": "View signing keys, signatures, provenance and attestations",
    "runtime.signing.manage": "Rotate and revoke signing keys",
    "runtime.deployment.view": "View deployments and deployment health",
    "runtime.deployment.create": "Create deployments",
    "runtime.deployment.deploy": "Deploy, suspend, resume and retire deployments",
    "runtime.deployment.rollback": "Roll back a deployment to a previous version",
    # Automated Rollback & Release Safety (Phase 3.7, ACT-SRS-M3 §11). The
    # elevated authority a *forced* rollback requires -- one that may name its
    # own target and bypass the designated-target requirement an ordinary
    # rollback fails closed on. Separated from "runtime.deployment.rollback"
    # because an override whose authority every release engineer already holds
    # would not be an override at all. It does not, and cannot, bypass the
    # kill switch.
    "runtime.deployment.force_rollback":
        "Force a rollback past normal preconditions (dangerous; requires justification)",
    # Distributed Scheduler (Phase 3.8, ACT-SRS-M3 §Phase-3.8). Job management
    # is separated from job *viewing* because a scheduled job is a standing
    # instruction to act on production without a human present -- being allowed
    # to read the run history is a much smaller grant than being allowed to arm
    # a new one.
    # Execution Worker Fleet (Phase 3.9, ACT-SRS-M3 §Phase-3.9). Split for the
    # same reason the scheduler's pair is split: reading the fleet is
    # observability, while draining a worker removes execution capacity from
    # production. "runtime.health.view" still covers the health/heartbeat read
    # model it always did; these govern the fleet itself.
    "runtime.worker.view": "View the execution worker fleet, its capacity and queue depth",
    "runtime.worker.manage": "Drain and stop execution workers",
    "runtime.scheduler.view": "View scheduled job definitions and run history",
    "runtime.scheduler.manage": "Create, edit, enable and disable scheduled jobs",
    # Environment & Promotion Model (Phase 3.2, ACT-SRS-M3 §3.2). Promoting a
    # deployment reuses "runtime.deployment.deploy" (below/above) rather than
    # a third code, since a promotion *is* a deployment operation; these two
    # are for the environment/promotion-path catalog itself.
    "runtime.environment.view": "View environments, their policy and configured promotion paths",
    "runtime.environment.manage": "Create and configure environments, their policy and promotion paths",
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
    # Phase 4.4 -- budgets. Two new codes, and `runtime.cost.view` deliberately
    # reused for the cost read model rather than shadowed by a synonym (its
    # description already named exactly this capability). Reading what was
    # spent and configuring a ceiling that can halt production are genuinely
    # different powers, and the second is a finance/admin decision rather than
    # an observability one -- which is why `manage` is separate from `view`
    # here even though 4.3 collapsed its own read permission into an existing
    # one.
    "runtime.budget.view": "View budgets and their utilization",
    "runtime.budget.manage": "Create and configure budgets that can halt execution when exhausted",
    # Phase 4.6 -- OpenTelemetry & metrics interoperability. Reading exporter
    # health and the metrics surface is an observability read, so it reuses
    # `runtime.telemetry.view`. Pointing the platform's telemetry at a third-
    # party collector is a different, material act -- it sends operational
    # metadata off-platform -- so configuring the export target has its own
    # manage code, and it is audited.
    "runtime.telemetry.export.manage": "Configure the OpenTelemetry export target (endpoint, on/off) for an environment",
    # Phase 4.7 -- SLOs and alerts. Reading an SLO, its evaluations, or an alert
    # is a derived-telemetry read and reuses `runtime.telemetry.view` (the 4.2/
    # 4.4/4.5 precedent). Two management powers are genuinely distinct: defining
    # a service objective (what "good" means) and working the alert queue
    # (acknowledge / resolve / suppress) are different jobs, often held by
    # different people, so they get separate codes rather than one broad one.
    "runtime.slo.manage": "Define, edit and evaluate runtime service objectives (SLOs)",
    "runtime.alert.manage": "Acknowledge, resolve and suppress runtime alerts",
    # Phase 4.8 -- telemetry privacy, retention & access governance. Three new
    # codes. `runtime.trace.content.view` is registered here for the first time
    # (4.1 and 4.2 deliberately left it unregistered, naming it in code so the
    # boundary had an owner; this phase is that owner). It is **strictly
    # stronger** than `runtime.telemetry.view`: seeing that a tool failed 34% of
    # the time is the metadata view; reading the PHI in that tool's arguments is
    # this. It is never implied by executing an agent or by holding the metadata
    # view -- a grant is deliberate, and every use is audited. The two
    # `telemetry_policy` codes gate configuring what is captured and for how
    # long (an admin/governance power), separate from the trace-content read.
    "runtime.trace.content.view":
        "Read trace content (prompts, tool arguments, tool results, model output) "
        "-- distinct from and stronger than the metadata trace view; audited on every use",
    "runtime.telemetry_policy.view":
        "View telemetry capture policies, effective capture mode and retention policies",
    "runtime.telemetry_policy.manage":
        "Configure telemetry capture policies (what content is captured) and "
        "retention policies (how long each telemetry class is kept)",
    "runtime.approval.review": "Approve or reject runtime approval requests",
    "runtime.kill_switch.execute": "Activate the runtime kill switch at any scope",
    # Phase 4.3 -- runtime governance. One code, not a family: this guards
    # writing the rules that can halt a running execution, which nothing
    # existing covers. Reading a decision reuses `runtime.execution.view`,
    # because "why did this execution stop" is a fact about an execution rather
    # than a separate capability -- a second code for it would leave operators
    # holding execution-view unable to answer the one question this phase
    # exists to answer (§16, avoid permission inflation).
    "runtime.governance.manage": "Configure runtime governance policies that can halt a running execution",
    # Per-organization model-provider credentials (Phase 5.7a.5).
    "runtime.provider.view": "View configured model-provider credentials (metadata and hint only, never the value)",
    "runtime.provider.manage": "Configure, replace, delete and test model-provider credentials",
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
    # Universal Agent Asset Model + Ownership (Phase 5.1 / M5.1 §11, §12).
    # ``claim`` is a distinct capability: taking first responsibility for a
    # discovered/unowned agent, not moving an already-held owner role
    # (``ownership.transfer``) nor a native lifecycle action (``register``).
    "runtime.agent.claim": "Claim responsibility for a discovered/unclaimed agent",
    "runtime.agent.control.manage":
        "Perform server-authoritative agent control-state transitions "
        "(register into scope, enroll into governance, and the safe reverses)",
    "runtime.agent.validation.view": "View agent validation runs and reports",
    "runtime.agent.duplicate.review": "Review and decide on detected duplicate agents",
    "runtime.agent.import": "Bulk-import agent registrations",
    "runtime.agent.export": "Export agent registrations",
    "runtime.agent.audit.view": "View agent registry audit and lifecycle history",
    # Enterprise Integration Framework -- Connector Abstraction & Lifecycle
    # (Phase 2.1.1 SRS ACT-INT-FR §5.1). No auth-specific permission yet --
    # authentication/credentials are Phase 2.1.2.
    "integration.connector.view": "View connector types, instances and their lifecycle history",
    "integration.connector.manage": "Create, configure, activate and disable connector instances",
    # External Identity Federation (Phase 2.3.1 SRS ACT-INT-FR-185). Federation
    # config includes the IdP's own public signing certificate/JWKS reference --
    # not secret, but integrity-critical (tampering with it is an authentication
    # bypass), so it is gated by this permission like any other admin-only config.
    "identity.federation.view": "View an organization's identity federation (SSO) configurations",
    "identity.federation.manage": "Create, configure and remove identity federation (SSO) connections",
    # Agent Discovery Framework (Phase 5.2 / M5.2). Two codes, mirroring the
    # connector precedent (`integration.connector.view`/`.manage`) exactly --
    # reading sources/runs/observations/findings vs. configuring a source,
    # triggering a sweep, or resolving a finding.
    "discovery.source.view":
        "View discovery sources, run history, observations and reconciliation/staleness findings",
    "discovery.source.manage":
        "Configure discovery sources, trigger a manual sweep, and resolve or dismiss findings",
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
