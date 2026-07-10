"""Authorization enums (Phase 4.3.1 §8, §9, §15, §23)."""

from __future__ import annotations

import enum


class RoleCategory(str, enum.Enum):
    """§9 — what kind of role this is."""

    SYSTEM = "SYSTEM"
    CUSTOM = "CUSTOM"
    ORGANIZATION = "ORGANIZATION"
    PROJECT = "PROJECT"
    RESOURCE = "RESOURCE"


class RoleStatus(str, enum.Enum):
    """§8 — role lifecycle. DELETED is a terminal soft-delete; rows are never
    hard-removed while assignments or audit history reference them."""

    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    UPDATED = "UPDATED"
    DEPRECATED = "DEPRECATED"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"

    @property
    def is_assignable_state(self) -> bool:
        """A role can only receive new assignments while it is live."""
        return self in (RoleStatus.CREATED, RoleStatus.ACTIVE, RoleStatus.UPDATED)


class AssignmentScope(str, enum.Enum):
    """§15 — how far a role assignment reaches."""

    GLOBAL = "GLOBAL"
    ORGANIZATION = "ORGANIZATION"
    DEPARTMENT = "DEPARTMENT"
    TEAM = "TEAM"
    PROJECT = "PROJECT"
    RESOURCE = "RESOURCE"


class AuthorizationDecision(str, enum.Enum):
    """Recorded on every authorization-audit row for a permission check."""

    ALLOW = "ALLOW"
    DENY = "DENY"


class AuthorizationEngineEvent(str, enum.Enum):
    """The events the Permission Engine generates while evaluating a decision
    (Phase 4.3.2 §27). The two outcome events are persisted on the decision; the
    pipeline-step events are generated as a per-decision trace and surfaced on the
    ``/authorization/check`` response for observability."""

    AUTHORIZATION_GRANTED = "AUTHORIZATION_GRANTED"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    PERMISSION_CACHE_REFRESHED = "PERMISSION_CACHE_REFRESHED"
    ROLE_RESOLVED = "ROLE_RESOLVED"
    WILDCARD_EXPANDED = "WILDCARD_EXPANDED"
    SCOPE_VALIDATED = "SCOPE_VALIDATED"
    CONFLICT_RESOLVED = "CONFLICT_RESOLVED"


class AuthorizationAuditEvent(str, enum.Enum):
    """§23 — the administrative change events this subsystem emits, plus the
    per-request decision event."""

    ROLE_CREATED = "ROLE_CREATED"
    ROLE_UPDATED = "ROLE_UPDATED"
    ROLE_ARCHIVED = "ROLE_ARCHIVED"
    ROLE_DELETED = "ROLE_DELETED"
    ROLE_ASSIGNED = "ROLE_ASSIGNED"
    ROLE_REMOVED = "ROLE_REMOVED"
    PERMISSION_CREATED = "PERMISSION_CREATED"
    PERMISSION_UPDATED = "PERMISSION_UPDATED"
    PERMISSION_DELETED = "PERMISSION_DELETED"
    PERMISSION_ASSIGNED = "PERMISSION_ASSIGNED"
    PERMISSION_REMOVED = "PERMISSION_REMOVED"
    ROLE_HIERARCHY_UPDATED = "ROLE_HIERARCHY_UPDATED"
    ROLE_HIERARCHY_REMOVED = "ROLE_HIERARCHY_REMOVED"
    AUTHORIZATION_DECISION = "AUTHORIZATION_DECISION"
