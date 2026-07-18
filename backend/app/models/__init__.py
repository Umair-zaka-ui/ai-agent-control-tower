"""SQLAlchemy ORM models.

Importing this package registers every model on ``Base.metadata`` which is
what Alembic autogenerate and ``create_all`` rely on.
"""

from app.models.abac import (
    ABACEvaluation,
    ABACPolicy,
    ABACPolicyException,
    ABACPolicyVersion,
    AttributeDefinition,
)
from app.models.access_review import AccessReviewCampaign, AccessReviewItem
from app.models.agent import Agent
from app.models.agent_action import AgentAction
from app.models.api_key import AgentApiKey
from app.models.approval import Approval, ApprovalComment
from app.models.audit_log import AuditLog
from app.models.governance import (
    ComplianceReport,
    GovernanceFinding,
    GovernanceRiskScore,
    PrivilegedAccountReview,
    RemediationAction,
    SoDRule,
)
from app.models.organization import Organization
from app.models.organization_hierarchy import (
    BusinessUnit,
    Delegation,
    Project,
    ResourceOwnership,
)
from app.models.permission import Permission
from app.models.resource_authorization import (
    OwnershipHistory,
    ProtectedResource,
    ResourceACLEntry,
    ResourceDelegation,
    ResourceShare,
)
from app.models.policy import Policy
from app.models.rbac import (
    AuthorizationAudit,
    AuthorizationDecision,
    PermissionCache,
    PermissionGroup,
    PermissionVersion,
    RbacPermission,
    Role,
    RoleHierarchy,
    RolePermission,
    UserRole,
)
from app.models.user import User

__all__ = [
    "AccessReviewCampaign",
    "AccessReviewItem",
    "Organization",
    "User",
    "Agent",
    "Permission",
    "AgentAction",
    "Approval",
    "ApprovalComment",
    "AuditLog",
    "AgentApiKey",
    "Policy",
    "Role",
    "RbacPermission",
    "RolePermission",
    "UserRole",
    "PermissionGroup",
    "RoleHierarchy",
    "AuthorizationAudit",
    "PermissionVersion",
    "PermissionCache",
    "AuthorizationDecision",
    "BusinessUnit",
    "Project",
    "ResourceOwnership",
    "Delegation",
    "ProtectedResource",
    "ResourceACLEntry",
    "ResourceShare",
    "OwnershipHistory",
    "ResourceDelegation",
    "ABACPolicy",
    "ABACPolicyVersion",
    "AttributeDefinition",
    "ABACEvaluation",
    "ABACPolicyException",
    "SoDRule",
    "GovernanceFinding",
    "RemediationAction",
    "GovernanceRiskScore",
    "ComplianceReport",
    "PrivilegedAccountReview",
]
