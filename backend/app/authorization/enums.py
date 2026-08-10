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
    # Administration portal (Phase 4.3.7 §22).
    ACCESS_REVIEW_CREATED = "ACCESS_REVIEW_CREATED"
    ACCESS_REVIEW_ACTIVATED = "ACCESS_REVIEW_ACTIVATED"
    ACCESS_REVIEW_ITEM_DECIDED = "ACCESS_REVIEW_ITEM_DECIDED"
    ACCESS_REVIEW_COMPLETED = "ACCESS_REVIEW_COMPLETED"
    ACCESS_REVIEW_ARCHIVED = "ACCESS_REVIEW_ARCHIVED"
    SIMULATION_EXECUTED = "SIMULATION_EXECUTED"
    DECISION_VIEWED = "DECISION_VIEWED"
    AUDIT_EXPORTED = "AUDIT_EXPORTED"
    # Identity Governance & Administration (Phase 4.3.8 §23).
    CERTIFICATION_CREATED = "CERTIFICATION_CREATED"
    CERTIFICATION_COMPLETED = "CERTIFICATION_COMPLETED"
    ACCESS_APPROVED = "ACCESS_APPROVED"
    ACCESS_REVOKED = "ACCESS_REVOKED"
    SOD_RULE_CREATED = "SOD_RULE_CREATED"
    SOD_RULE_ACTIVATED = "SOD_RULE_ACTIVATED"
    SOD_VIOLATION_FOUND = "SOD_VIOLATION_FOUND"
    TOXIC_PERMISSION_FOUND = "TOXIC_PERMISSION_FOUND"
    ORPHANED_ACCOUNT_DETECTED = "ORPHANED_ACCOUNT_DETECTED"
    PRIVILEGED_REVIEW_COMPLETED = "PRIVILEGED_REVIEW_COMPLETED"
    GOVERNANCE_FINDING_RESOLVED = "GOVERNANCE_FINDING_RESOLVED"
    REMEDIATION_CREATED = "REMEDIATION_CREATED"
    REMEDIATION_EXECUTED = "REMEDIATION_EXECUTED"
    RISK_SCORE_COMPUTED = "RISK_SCORE_COMPUTED"
    COMPLIANCE_REPORT_GENERATED = "COMPLIANCE_REPORT_GENERATED"
    # Agent Runtime & Lifecycle Management (Phase 5.0 §76).
    RUNTIME_AGENT_REGISTERED = "RUNTIME_AGENT_REGISTERED"
    RUNTIME_AGENT_ACTIVATED = "RUNTIME_AGENT_ACTIVATED"
    RUNTIME_AGENT_SUSPENDED = "RUNTIME_AGENT_SUSPENDED"
    RUNTIME_AGENT_ARCHIVED = "RUNTIME_AGENT_ARCHIVED"
    RUNTIME_AGENT_RETIRED = "RUNTIME_AGENT_RETIRED"
    RUNTIME_VERSION_CREATED = "RUNTIME_VERSION_CREATED"
    RUNTIME_VERSION_PUBLISHED = "RUNTIME_VERSION_PUBLISHED"
    RUNTIME_VERSION_DEPRECATED = "RUNTIME_VERSION_DEPRECATED"
    RUNTIME_VERSION_REVOKED = "RUNTIME_VERSION_REVOKED"
    RUNTIME_DEPLOYMENT_CREATED = "RUNTIME_DEPLOYMENT_CREATED"
    RUNTIME_DEPLOYMENT_ACTIVE = "RUNTIME_DEPLOYMENT_ACTIVE"
    RUNTIME_DEPLOYMENT_FAILED = "RUNTIME_DEPLOYMENT_FAILED"
    RUNTIME_DEPLOYMENT_SUSPENDED = "RUNTIME_DEPLOYMENT_SUSPENDED"
    RUNTIME_DEPLOYMENT_ROLLED_BACK = "RUNTIME_DEPLOYMENT_ROLLED_BACK"
    RUNTIME_DEPLOYMENT_RETIRED = "RUNTIME_DEPLOYMENT_RETIRED"
    # Phase 3.1 (ACT-SRS-M3 §3.1, §13) -- the new 15-state deployment
    # lifecycle's own transitions not already covered by an event above
    # (CREATED/ACTIVE/FAILED/RETIRED are reused verbatim for the new
    # machine's identically-named states).
    RUNTIME_DEPLOYMENT_VALIDATING = "RUNTIME_DEPLOYMENT_VALIDATING"
    RUNTIME_DEPLOYMENT_VALIDATION_FAILED = "RUNTIME_DEPLOYMENT_VALIDATION_FAILED"
    RUNTIME_DEPLOYMENT_READY = "RUNTIME_DEPLOYMENT_READY"
    RUNTIME_DEPLOYMENT_PENDING_APPROVAL = "RUNTIME_DEPLOYMENT_PENDING_APPROVAL"
    RUNTIME_DEPLOYMENT_APPROVED = "RUNTIME_DEPLOYMENT_APPROVED"
    RUNTIME_DEPLOYMENT_REJECTED = "RUNTIME_DEPLOYMENT_REJECTED"
    RUNTIME_DEPLOYMENT_DEPLOYING = "RUNTIME_DEPLOYMENT_DEPLOYING"
    RUNTIME_DEPLOYMENT_PAUSED = "RUNTIME_DEPLOYMENT_PAUSED"
    RUNTIME_DEPLOYMENT_RESUMED = "RUNTIME_DEPLOYMENT_RESUMED"
    RUNTIME_DEPLOYMENT_DEGRADED = "RUNTIME_DEPLOYMENT_DEGRADED"
    RUNTIME_DEPLOYMENT_ROLLING_BACK = "RUNTIME_DEPLOYMENT_ROLLING_BACK"
    RUNTIME_DEPLOYMENT_SUPERSEDED = "RUNTIME_DEPLOYMENT_SUPERSEDED"
    RUNTIME_EXECUTION_CREATED = "RUNTIME_EXECUTION_CREATED"
    RUNTIME_EXECUTION_DENIED = "RUNTIME_EXECUTION_DENIED"
    RUNTIME_EXECUTION_APPROVAL_REQUIRED = "RUNTIME_EXECUTION_APPROVAL_REQUIRED"
    RUNTIME_EXECUTION_SUCCEEDED = "RUNTIME_EXECUTION_SUCCEEDED"
    RUNTIME_EXECUTION_FAILED = "RUNTIME_EXECUTION_FAILED"
    RUNTIME_EXECUTION_CANCELLED = "RUNTIME_EXECUTION_CANCELLED"
    RUNTIME_EXECUTION_DEAD_LETTERED = "RUNTIME_EXECUTION_DEAD_LETTERED"
    RUNTIME_CAPABILITY_ASSIGNED = "RUNTIME_CAPABILITY_ASSIGNED"
    RUNTIME_CAPABILITY_REVOKED = "RUNTIME_CAPABILITY_REVOKED"
    RUNTIME_TOOL_ASSIGNED = "RUNTIME_TOOL_ASSIGNED"
    RUNTIME_TOOL_REVOKED = "RUNTIME_TOOL_REVOKED"
    RUNTIME_TOOL_CALL_DENIED = "RUNTIME_TOOL_CALL_DENIED"
    # HTTP tool execution & egress control (Phase 5.6a.1). ``_DENIED`` is
    # security-severity (CRITICAL) -- an egress denial is a signal someone
    # may be probing the SSRF boundary, routed to alerting.
    RUNTIME_TOOL_INVOKED = "RUNTIME_TOOL_INVOKED"
    RUNTIME_TOOL_EGRESS_DENIED = "RUNTIME_TOOL_EGRESS_DENIED"
    # Tool schema validation & resilience (Phase 5.6a.2) -- this platform's
    # concrete realization of the SRS's conceptual "execution.tool.failed"
    # event, matching the existing RUNTIME_* naming convention (the same
    # relationship RUNTIME_EXECUTION_FAILED already has to "the execution
    # failed"). Emitted whenever a tool call ends ToolCall.status="FAILED"
    # (schema violation, exhausted retries, timeout, oversized response,
    # an open circuit, or the concurrency ceiling) -- never for "DENIED"
    # (TOOL_EGRESS_DENIED/TOOL_ACTION_NOT_ALLOWED/etc. keep their own,
    # unchanged 5.6a.1 event).
    RUNTIME_TOOL_FAILED = "RUNTIME_TOOL_FAILED"
    # Model-driven tool invocation loop (Phase 5.6a.3) -- this platform's
    # RUNTIME_*-convention realization of the SRS's conceptual
    # "execution.loop.iteration"/"execution.loop.terminated" events.
    # `_ITERATION` is per model turn (INFO); `_TERMINATED` carries the
    # specific `termination_reason` and is CRITICAL only when it reflects a
    # loop-safety cap breach (MAX_ITERATIONS/TOKEN_BUDGET/WALL_CLOCK/
    # REPEATED_CALL) rather than a normal COMPLETED finish.
    RUNTIME_LOOP_ITERATION = "RUNTIME_LOOP_ITERATION"
    RUNTIME_LOOP_TERMINATED = "RUNTIME_LOOP_TERMINATED"
    RUNTIME_LIMIT_EXCEEDED = "RUNTIME_LIMIT_EXCEEDED"
    RUNTIME_KILL_SWITCH_ACTIVATED = "RUNTIME_KILL_SWITCH_ACTIVATED"
    RUNTIME_ROLLBACK_COMPLETED = "RUNTIME_ROLLBACK_COMPLETED"
    # Enterprise Agent Registry (Phase 5.1 §67).
    RUNTIME_AGENT_UPDATED = "RUNTIME_AGENT_UPDATED"
    RUNTIME_AGENT_VALIDATION_STARTED = "RUNTIME_AGENT_VALIDATION_STARTED"
    RUNTIME_AGENT_VALIDATION_PASSED = "RUNTIME_AGENT_VALIDATION_PASSED"
    RUNTIME_AGENT_VALIDATION_FAILED = "RUNTIME_AGENT_VALIDATION_FAILED"
    RUNTIME_AGENT_APPROVAL_REQUESTED = "RUNTIME_AGENT_APPROVAL_REQUESTED"
    RUNTIME_AGENT_APPROVED = "RUNTIME_AGENT_APPROVED"
    RUNTIME_AGENT_REJECTED = "RUNTIME_AGENT_REJECTED"
    RUNTIME_AGENT_RESUMED = "RUNTIME_AGENT_RESUMED"
    RUNTIME_AGENT_DEPRECATED = "RUNTIME_AGENT_DEPRECATED"
    RUNTIME_AGENT_RESTORED = "RUNTIME_AGENT_RESTORED"
    RUNTIME_AGENT_OWNER_TRANSFERRED = "RUNTIME_AGENT_OWNER_TRANSFERRED"
    RUNTIME_AGENT_IDENTITY_ASSOCIATED = "RUNTIME_AGENT_IDENTITY_ASSOCIATED"
    RUNTIME_AGENT_IDENTITY_REPLACED = "RUNTIME_AGENT_IDENTITY_REPLACED"
    RUNTIME_AGENT_DUPLICATE_DETECTED = "RUNTIME_AGENT_DUPLICATE_DETECTED"
    RUNTIME_AGENT_DUPLICATE_REVIEWED = "RUNTIME_AGENT_DUPLICATE_REVIEWED"
    RUNTIME_AGENT_IMPORT_STARTED = "RUNTIME_AGENT_IMPORT_STARTED"
    RUNTIME_AGENT_IMPORT_COMPLETED = "RUNTIME_AGENT_IMPORT_COMPLETED"
    RUNTIME_AGENT_EXPORT_STARTED = "RUNTIME_AGENT_EXPORT_STARTED"
    RUNTIME_AGENT_EXPORT_COMPLETED = "RUNTIME_AGENT_EXPORT_COMPLETED"
    # Enterprise Versioning & Release Management (Phase 5.2 Part 1).
    RUNTIME_VERSION_RETIRED = "RUNTIME_VERSION_RETIRED"
    RUNTIME_VERSION_ARTIFACT_ADDED = "RUNTIME_VERSION_ARTIFACT_ADDED"
    RUNTIME_VERSION_NOTE_ADDED = "RUNTIME_VERSION_NOTE_ADDED"
    RUNTIME_VERSION_RELEASE_METADATA_UPDATED = "RUNTIME_VERSION_RELEASE_METADATA_UPDATED"
    RUNTIME_VERSION_ROLLBACK_TARGET_SET = "RUNTIME_VERSION_ROLLBACK_TARGET_SET"
    # Per-organization model-provider credentials (Phase 5.7a.5). ``meta``
    # carries the provider identifier and action only -- never the secret
    # value or even its encrypted form (ACT-MDL-FR-081).
    RUNTIME_PROVIDER_CREDENTIAL_UPDATED = "RUNTIME_PROVIDER_CREDENTIAL_UPDATED"
    RUNTIME_PROVIDER_CREDENTIAL_DELETED = "RUNTIME_PROVIDER_CREDENTIAL_DELETED"
    # Enterprise Integration Framework -- Connector Abstraction & Lifecycle
    # (Phase 2.1.1, ACT-INT-FR-010). One event for every lifecycle
    # transition (configure/activate/disable/mark_failed) -- `meta` carries
    # `event`/`from_state`/`to_state`/`reason`, mirroring how
    # RUNTIME_LOOP_TERMINATED carries its own transition detail in `meta`
    # rather than needing a separate event per transition kind.
    INTEGRATION_CONNECTOR_STATE_CHANGED = "INTEGRATION_CONNECTOR_STATE_CHANGED"
    # Connector Authentication Framework (Phase 2.1.2, ACT-INT-FR-020..028).
    # `meta` carries connector_instance_id/auth_scheme only -- never a
    # credential value or its ciphertext, mirroring
    # RUNTIME_PROVIDER_CREDENTIAL_UPDATED's own redaction discipline.
    INTEGRATION_CONNECTOR_CREDENTIAL_UPDATED = "INTEGRATION_CONNECTOR_CREDENTIAL_UPDATED"
    INTEGRATION_CONNECTOR_CREDENTIAL_DELETED = "INTEGRATION_CONNECTOR_CREDENTIAL_DELETED"
    INTEGRATION_CONNECTOR_CREDENTIAL_VALIDATED = "INTEGRATION_CONNECTOR_CREDENTIAL_VALIDATED"
    # Connector Registry & Health (Phase 2.1.3, ACT-INT-FR-042..047).
    # Emitted for every health check (healthy or not); `meta` carries
    # `result`/`reachable`/`auth_valid`/`check_type` and a safe `reason`
    # only -- never credential/token material. The alert-worthy signal
    # for a `failed` transition specifically is
    # INTEGRATION_CONNECTOR_STATE_CHANGED (reused unchanged from 2.1.1,
    # now carrying a `severity` field -- see ConnectorService._transition),
    # not a second, dedicated event.
    INTEGRATION_CONNECTOR_HEALTH_CHECKED = "INTEGRATION_CONNECTOR_HEALTH_CHECKED"
    # Generic File & Object Storage Connector (Phase 2.2.3, ACT-INT-FR-145).
    # Emitted for every object access attempt through the tool-invocation
    # bridge -- allowed or denied, read or write -- `meta` carries
    # `backend`/`scope_name`/`operation`/`path` (the *validated* path, never
    # the raw supplied string)/`size_bytes`/`outcome`. Never a credential.
    # This is 2.2.x's first invocation-level audit event -- 2.2.1/2.2.2's own
    # tool bridges did not audit individual calls, since neither build
    # prompt required it; this one (FR-145) explicitly does.
    INTEGRATION_CONNECTOR_OBJECT_ACCESSED = "INTEGRATION_CONNECTOR_OBJECT_ACCESSED"
