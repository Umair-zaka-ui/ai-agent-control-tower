"""SQLAlchemy ORM models.

Importing this package registers every model on ``Base.metadata`` which is
what Alembic autogenerate and ``create_all`` rely on.
"""

from app.models.agent import Agent
from app.models.agent_action import AgentAction
from app.models.api_key import AgentApiKey
from app.models.approval import Approval, ApprovalComment
from app.models.audit_log import AuditLog
from app.models.organization import Organization
from app.models.permission import Permission
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
]
