"""Resource-based authorization enums (Phase 4.3.4 §3, §9, §10, §12, §23)."""

from __future__ import annotations

import enum


class ResourceType(str, enum.Enum):
    """§3 — the built-in resource categories. ``resources.resource_type`` stays a
    free-form string so future types register without an engine change; this enum
    is the catalog the UI offers."""

    AI_AGENT = "ai_agent"
    PROMPT_TEMPLATE = "prompt_template"
    WORKFLOW = "workflow"
    POLICY = "policy"
    APPROVAL_REQUEST = "approval_request"
    KNOWLEDGE_BASE = "knowledge_base"
    MODEL_CONFIGURATION = "model_configuration"
    DATASET = "dataset"
    DASHBOARD = "dashboard"
    CONNECTOR = "connector"
    API_KEY = "api_key"
    ORGANIZATION = "organization"
    PROJECT = "project"
    MARKETPLACE_ASSET = "marketplace_asset"
    EVALUATION_CONFIGURATION = "evaluation_configuration"


class OwnerType(str, enum.Enum):
    """§6 — who owns a resource."""

    USER = "USER"
    TEAM = "TEAM"
    DEPARTMENT = "DEPARTMENT"
    ORGANIZATION = "ORGANIZATION"
    SERVICE_ACCOUNT = "SERVICE_ACCOUNT"


class VisibilityLevel(str, enum.Enum):
    """§9 — baseline read access before ACLs and shares."""

    PRIVATE = "PRIVATE"
    TEAM = "TEAM"
    DEPARTMENT = "DEPARTMENT"
    ORGANIZATION = "ORGANIZATION"
    PUBLIC_INTERNAL = "PUBLIC_INTERNAL"


class PrincipalType(str, enum.Enum):
    """§10 — who an ACL entry (or share) can name."""

    USER = "USER"
    ROLE = "ROLE"
    TEAM = "TEAM"
    DEPARTMENT = "DEPARTMENT"
    ORGANIZATION = "ORGANIZATION"
    SERVICE_ACCOUNT = "SERVICE_ACCOUNT"


class ACLEffect(str, enum.Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class ShareAccessLevel(str, enum.Enum):
    """§12 — sharing modes, weakest to strongest."""

    READ = "READ"
    COMMENT = "COMMENT"
    EXECUTE = "EXECUTE"
    EDIT = "EDIT"
    MANAGE = "MANAGE"


class ResourceStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    # System-level resources carry the §22 protection: owners cannot deny
    # platform administrators on them.
    SYSTEM = "SYSTEM"


class DelegationStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class ResourceAuditEvent(str, enum.Enum):
    """§23 — recorded on the shared ``authorization_audit`` table."""

    RESOURCE_REGISTERED = "RESOURCE_REGISTERED"
    RESOURCE_SHARED = "RESOURCE_SHARED"
    RESOURCE_UNSHARED = "RESOURCE_UNSHARED"
    RESOURCE_SHARE_UPDATED = "RESOURCE_SHARE_UPDATED"
    RESOURCE_OWNER_CHANGED = "RESOURCE_OWNER_CHANGED"
    RESOURCE_ACL_CREATED = "RESOURCE_ACL_CREATED"
    RESOURCE_ACL_UPDATED = "RESOURCE_ACL_UPDATED"
    RESOURCE_ACL_DELETED = "RESOURCE_ACL_DELETED"
    RESOURCE_DELEGATED = "RESOURCE_DELEGATED"
    RESOURCE_DELEGATION_REVOKED = "RESOURCE_DELEGATION_REVOKED"
    RESOURCE_POLICY_UPDATED = "RESOURCE_POLICY_UPDATED"
    RESOURCE_VISIBILITY_CHANGED = "RESOURCE_VISIBILITY_CHANGED"
    RESOURCE_ACCESS_GRANTED = "RESOURCE_ACCESS_GRANTED"
    RESOURCE_ACCESS_DENIED = "RESOURCE_ACCESS_DENIED"
