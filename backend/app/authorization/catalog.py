"""Permission groups, the enriched permission catalog, and the built-in role
taxonomy (Phase 4.3.1 §7, §11, §12, §13, §16, §17).

The permission *codes* remain single-sourced in ``app.services.rbac_service``
(``PERMISSION_CATALOG``); here we add the enterprise metadata around them —
which domain group a permission belongs to, its resource/action split, and the
built-in roles + hierarchy that ship with the platform.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.authorization.enums import RoleCategory
from app.services.rbac_service import PERMISSION_CATALOG, SYSTEM_ROLE_PERMISSIONS


# --- Permission groups (§12) ----------------------------------------------- #
@dataclass(frozen=True)
class PermissionGroupDef:
    name: str
    display_name: str
    description: str
    sort_order: int


PERMISSION_GROUPS: tuple[PermissionGroupDef, ...] = (
    PermissionGroupDef("agents", "Agents", "Register, operate and retire AI agents", 10),
    PermissionGroupDef("policies", "Policies", "Author, approve and publish policies", 20),
    PermissionGroupDef("approvals", "Approvals", "Review and route the approval queue", 30),
    PermissionGroupDef("audit", "Audit", "Read and export audit and compliance data", 40),
    PermissionGroupDef("security", "Security", "Sessions, credentials, recovery and protection", 50),
    PermissionGroupDef("organizations", "Organizations", "Users, invitations and org management", 60),
    PermissionGroupDef("analytics", "Analytics", "Operational and executive dashboards", 70),
    PermissionGroupDef("authorization", "Authorization", "Roles, permissions and assignments", 80),
    PermissionGroupDef("general", "General", "Uncategorised permissions", 999),
)

# resource prefix (the part before the first dot) -> group name.
_RESOURCE_GROUP: dict[str, str] = {
    "agent": "agents",
    "apikey": "agents",
    "agent_action": "agents",
    "policy": "policies",
    "approval": "approvals",
    "audit": "audit",
    "dashboard": "analytics",
    "analytics": "analytics",
    "security": "security",
    "session": "security",
    "credential": "security",
    "recovery": "security",
    "user": "organizations",
    "invitation": "organizations",
    "organization": "organizations",
    "role": "authorization",
    "permission": "authorization",
    "rbac": "authorization",
}


def split_code(code: str) -> tuple[str, str]:
    """``"agent.create"`` -> ``("agent", "create")``; a code with no dot maps its
    whole value to the resource and ``"*"`` (wildcard) to the action."""
    resource, _, action = code.partition(".")
    return resource, (action or "*")


def group_for_code(code: str) -> str:
    resource, _ = split_code(code)
    return _RESOURCE_GROUP.get(resource, "general")


def display_name_for_code(code: str) -> str:
    resource, action = split_code(code)
    return f"{resource.replace('_', ' ').title()}: {action}"


# --- Built-in role taxonomy (§7, §16) -------------------------------------- #
# Permission-set shortcuts derived from the single-source catalog.
_ALL = set(PERMISSION_CATALOG)
_READ_ONLY = {
    "agent.view",
    "policy.view",
    "audit.view",
    "dashboard.view",
    "agent_action.view",
    "approval.view",
    "analytics.view",
}
_SECURITY = {
    "security.protection",
    "session.view",
    "session.revoke",
    "credential.reset",
    "credential.dashboard",
    "recovery.view",
    "audit.view",
    "audit.export",
}
_AI_OPS = {
    "agent.create",
    "agent.view",
    "agent.update",
    "apikey.create",
    "apikey.revoke",
    "agent_action.create",
    "agent_action.view",
    "policy.view",
    "dashboard.view",
}
_AI_REVIEW = {
    "approval.view",
    "approval.review",
    "approval.escalate",
    "approval.assign",
    "agent.view",
    "policy.view",
    "dashboard.view",
}
_ORG_ADMIN = (_ALL - {"rbac.manage", "role.manage", "analytics.executive"}) | {"role.view"}


@dataclass(frozen=True)
class BuiltinRoleDef:
    name: str
    display_name: str
    description: str
    category: RoleCategory
    priority: int
    permissions: set[str]
    is_assignable: bool = True
    # Roles this role is senior to; it inherits their permissions (§17).
    children: tuple[str, ...] = field(default_factory=tuple)


# Priorities per §16 (higher = wins conflict resolution). The role hierarchy edges
# are expressed via ``children``: a parent (senior) role inherits its children's
# permissions. Kept acyclic by construction and enforced at write time.
BUILTIN_ROLES: tuple[BuiltinRoleDef, ...] = (
    # Platform
    BuiltinRoleDef("ROLE_PLATFORM_OWNER", "Platform Owner", "Full, unrestricted platform control",
                   RoleCategory.SYSTEM, 100, set(_ALL), children=("ROLE_PLATFORM_ADMIN",)),
    BuiltinRoleDef("ROLE_PLATFORM_ADMIN", "Platform Admin", "Administer the platform (except ownership transfer)",
                   RoleCategory.SYSTEM, 90, _ALL - {"role.manage"},
                   children=("ROLE_SECURITY_ADMIN", "ROLE_ORG_ADMIN", "ROLE_COMPLIANCE_ADMIN")),
    BuiltinRoleDef("ROLE_SECURITY_ADMIN", "Security Admin", "Security operations: locks, sessions, recovery, audit",
                   RoleCategory.SYSTEM, 80, set(_SECURITY), children=("ROLE_AUDITOR",)),
    BuiltinRoleDef("ROLE_AUDITOR", "Auditor", "Read and export audit, compliance and analytics",
                   RoleCategory.SYSTEM, 40, {"audit.view", "audit.export", "analytics.view", "dashboard.view"},
                   children=("ROLE_VIEWER",)),
    # Identity Governance & Administration (Phase 4.3.8 §11) — tracked privileged role.
    BuiltinRoleDef("ROLE_COMPLIANCE_ADMIN", "Compliance Admin",
                   "Run certification campaigns, SoD/toxic detection, remediation and compliance evidence",
                   RoleCategory.SYSTEM, 78,
                   {"governance.dashboard.view", "governance.certification.manage",
                    "governance.sod.manage", "governance.sod.view", "governance.toxic.manage",
                    "governance.privileged.manage", "governance.orphaned.manage",
                    "governance.findings.manage", "governance.remediation.manage",
                    "governance.compliance.view", "governance.analytics.view",
                    "audit.view", "audit.export"},
                   children=("ROLE_AUDITOR",)),
    BuiltinRoleDef("ROLE_SUPPORT_ENGINEER", "Support Engineer", "Read-mostly support access",
                   RoleCategory.SYSTEM, 35, _READ_ONLY | {"session.view"}, children=("ROLE_VIEWER",)),
    # AI operations
    BuiltinRoleDef("ROLE_AI_OPERATOR", "AI Operator", "Operate AI agents and their keys",
                   RoleCategory.SYSTEM, 50, set(_AI_OPS), children=("ROLE_VIEWER",)),
    BuiltinRoleDef("ROLE_AI_REVIEWER", "AI Reviewer", "Review agent actions and approvals",
                   RoleCategory.SYSTEM, 45, set(_AI_REVIEW), children=("ROLE_VIEWER",)),
    BuiltinRoleDef("ROLE_POLICY_MANAGER", "Policy Manager", "Author, edit and publish policies",
                   RoleCategory.SYSTEM, 55, {"policy.create", "policy.view", "policy.edit", "policy.delete",
                                            "dashboard.view"}, children=("ROLE_VIEWER",)),
    BuiltinRoleDef("ROLE_MODEL_MANAGER", "Model Manager", "Manage AI agents/models and their keys",
                   RoleCategory.SYSTEM, 50, {"agent.view", "agent.update", "agent.create",
                                            "apikey.create", "apikey.revoke", "dashboard.view"},
                   children=("ROLE_VIEWER",)),
    BuiltinRoleDef("ROLE_APPROVAL_MANAGER", "Approval Manager", "Own the approval queue",
                   RoleCategory.SYSTEM, 55, {"approval.view", "approval.review", "approval.escalate",
                                            "approval.assign", "dashboard.view"}, children=("ROLE_VIEWER",)),
    # Organization
    BuiltinRoleDef("ROLE_ORG_OWNER", "Organization Owner", "Own an organization",
                   RoleCategory.ORGANIZATION, 75, set(_ORG_ADMIN), children=("ROLE_ORG_ADMIN",)),
    BuiltinRoleDef("ROLE_ORG_ADMIN", "Organization Admin", "Administer an organization",
                   RoleCategory.ORGANIZATION, 70, set(_ORG_ADMIN), children=("ROLE_DEPARTMENT_MANAGER",)),
    BuiltinRoleDef("ROLE_DEPARTMENT_MANAGER", "Department Manager", "Manage a department",
                   RoleCategory.ORGANIZATION, 60, _AI_OPS | {"user.view", "invitation.view"},
                   children=("ROLE_TEAM_LEAD",)),
    BuiltinRoleDef("ROLE_TEAM_LEAD", "Team Lead", "Lead a team",
                   RoleCategory.ORGANIZATION, 40, _AI_REVIEW | {"user.view"}, children=("ROLE_USER",)),
    BuiltinRoleDef("ROLE_USER", "User", "Standard authenticated user",
                   RoleCategory.ORGANIZATION, 20, {"agent.view", "policy.view", "dashboard.view",
                                                   "agent_action.view"}, children=("ROLE_VIEWER",)),
    # Read only
    BuiltinRoleDef("ROLE_VIEWER", "Viewer", "Read-only access",
                   RoleCategory.SYSTEM, 10, set(_READ_ONLY)),
    BuiltinRoleDef("ROLE_REPORT_READER", "Report Reader", "Read reports and dashboards",
                   RoleCategory.SYSTEM, 15, {"dashboard.view", "analytics.view"}),
    BuiltinRoleDef("ROLE_ANALYTICS_VIEWER", "Analytics Viewer", "Read analytics dashboards",
                   RoleCategory.SYSTEM, 15, {"analytics.view", "analytics.operations", "dashboard.view"}),
)

BUILTIN_ROLE_BY_NAME: dict[str, BuiltinRoleDef] = {r.name: r for r in BUILTIN_ROLES}

# Hierarchy edges (parent_name, child_name) derived from ``children`` above.
ROLE_HIERARCHY_EDGES: tuple[tuple[str, str], ...] = tuple(
    (role.name, child)
    for role in BUILTIN_ROLES
    for child in role.children
)


def legacy_role_priority(name: str) -> int:
    """Priority for the four legacy system roles (SUPER_ADMIN/ADMIN/REVIEWER/VIEWER)
    so they sort sensibly alongside the new taxonomy."""
    return {
        "SUPER_ADMIN": 95,
        "ADMIN": 85,
        "REVIEWER": 45,
        "VIEWER": 10,
    }.get(name, 50)


__all__ = [
    "PERMISSION_GROUPS",
    "PermissionGroupDef",
    "BuiltinRoleDef",
    "BUILTIN_ROLES",
    "BUILTIN_ROLE_BY_NAME",
    "ROLE_HIERARCHY_EDGES",
    "split_code",
    "group_for_code",
    "display_name_for_code",
    "legacy_role_priority",
    "SYSTEM_ROLE_PERMISSIONS",
]
