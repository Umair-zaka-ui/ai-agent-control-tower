"""Pydantic schemas for the Agent Runtime API (Phase 5.0 §66)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

_ENVIRONMENT = Field(pattern="^(DEVELOPMENT|TEST|STAGING|PRODUCTION|SANDBOX)$")
_STRATEGY = Field(default="RECREATE", pattern="^(RECREATE|ROLLING|CANARY|BLUE_GREEN)$")
_PRIORITY = Field(default="NORMAL", pattern="^(LOW|NORMAL|HIGH|CRITICAL)$")


# --------------------------------------------------------------------------- #
# Agent definitions (§7.2)
# --------------------------------------------------------------------------- #
class AgentDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    name: str
    description: str | None
    framework: str
    framework_version: str | None
    entrypoint_type: str
    entrypoint: str
    runtime_language: str | None
    system_instructions: str | None
    configuration_schema: dict | None
    input_schema: dict | None
    output_schema: dict | None
    capability_declarations: list
    tool_declarations: list
    model_requirements: dict
    memory_requirements: dict
    data_requirements: dict
    network_requirements: dict
    secret_requirements: dict
    runtime_requirements: dict
    metadata: dict | None = Field(validation_alias="extra_metadata")
    created_at: datetime


# --------------------------------------------------------------------------- #
# Agent versions (§7.3, §11, §12)
# --------------------------------------------------------------------------- #
class AgentVersionCreate(BaseModel):
    definition_id: uuid.UUID | None = None
    # Phase 5.2 Part 1 §15-16 — omit to auto-derive (monotonic patch bump,
    # or 0.1.0 for the agent's first version); if supplied, must be a valid,
    # strictly-increasing, non-duplicate MAJOR.MINOR.PATCH value.
    semantic_version: str | None = Field(default=None, max_length=20)
    # §9, §26 — one of the agent_release_channels catalog names (defaults to
    # the catalog default, STABLE).
    release_channel: str | None = Field(default=None, max_length=30)
    prompt_snapshot: dict | None = None
    model_configuration: dict = Field(default_factory=dict)
    capability_ids: list[uuid.UUID] = Field(default_factory=list)
    tool_ids: list[uuid.UUID] = Field(default_factory=list)
    policy_snapshot: dict | None = None
    release_notes: str | None = None


class AgentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    definition_id: uuid.UUID
    version: int
    semantic_version: str
    status: str
    configuration_snapshot: dict
    prompt_snapshot: dict | None
    model_configuration: dict
    capabilities_snapshot: list
    tools_snapshot: list
    policy_snapshot: dict | None
    checksum: str
    release_notes: str | None
    created_by: uuid.UUID | None
    created_at: datetime
    published_at: datetime | None
    deprecated_at: datetime | None
    # Phase 5.2 Part 1 — release-management foundation.
    release_channel_id: uuid.UUID | None
    compatibility_level: str
    compatibility_baseline_id: uuid.UUID | None
    compatibility_analyzed_at: datetime | None
    signature_id: str | None
    snapshot_reference: str | None
    parent_version_id: uuid.UUID | None
    rollback_target_id: uuid.UUID | None
    superseded_by_id: uuid.UUID | None
    release_branch: str
    reviewed_by: uuid.UUID | None
    revoked_reason: str | None
    retired_at: datetime | None
    # Phase 5.2.4 — signing & provenance.
    checksum_algorithm: str
    signed_at: datetime | None
    manifest_digest: str | None


# --------------------------------------------------------------------------- #
# Deployments (§7.4, §14, §15)
# --------------------------------------------------------------------------- #
class DeploymentCreate(BaseModel):
    agent_version_id: uuid.UUID
    environment: str = _ENVIRONMENT
    deployment_strategy: str = _STRATEGY
    desired_replicas: int = Field(default=1, ge=0, le=100)
    configuration: dict = Field(default_factory=dict)
    secret_references: dict = Field(default_factory=dict)
    runtime_limits: dict = Field(default_factory=dict)


class DeploymentRollbackRequest(BaseModel):
    target_version_id: uuid.UUID


class DeploymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    agent_version_id: uuid.UUID
    organization_id: uuid.UUID
    environment: str
    deployment_strategy: str
    status: str
    desired_replicas: int
    active_replicas: int
    configuration: dict
    runtime_limits: dict
    health_status: str
    deployed_by: uuid.UUID | None
    deployed_at: datetime | None
    updated_at: datetime
    retired_at: datetime | None


class DeploymentHealthRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    deployment_id: uuid.UUID
    worker_id: str | None
    status: str
    metrics: dict | None
    checked_at: datetime


class HeartbeatSubmit(BaseModel):
    worker_id: str = Field(min_length=1, max_length=100)
    status: str = Field(default="HEALTHY", pattern="^(HEALTHY|DEGRADED|UNHEALTHY|OFFLINE)$")
    metrics: dict = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Executions (§7.5, §26, §27)
# --------------------------------------------------------------------------- #
class ExecutionCreate(BaseModel):
    agent_id: uuid.UUID
    deployment_id: uuid.UUID | None = None
    input_payload: dict = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=150)
    correlation_id: str | None = Field(default=None, max_length=100)
    priority: str = _PRIORITY


class AgentSelfExecutionCreate(BaseModel):
    """§29, §31 — an agent (API-key authenticated) requesting an execution
    of itself. No ``agent_id`` field: the target is always the authenticated
    agent, never a request-supplied value."""

    deployment_id: uuid.UUID | None = None
    input_payload: dict = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=150)
    correlation_id: str | None = Field(default=None, max_length=100)
    priority: str = _PRIORITY


class ExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    agent_id: uuid.UUID
    agent_version_id: uuid.UUID
    deployment_id: uuid.UUID | None
    trigger_type: str
    triggered_by_identity_id: uuid.UUID | None
    parent_execution_id: uuid.UUID | None
    correlation_id: str | None
    idempotency_key: str | None
    input_payload: dict
    output_payload: dict | None
    status: str
    decision: str | None
    risk_score: int | None
    priority: str
    queued_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    attempt_count: int
    cancel_requested: bool
    error_code: str | None
    error_message: str | None
    model_usage: dict | None
    tool_usage: dict | None
    cost: float
    created_at: datetime
    updated_at: datetime


class ExecutionAttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    execution_id: uuid.UUID
    attempt_number: int
    worker_id: str | None
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    error_code: str | None
    error_message: str | None
    created_at: datetime


class ToolCallRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    execution_id: uuid.UUID
    agent_id: uuid.UUID
    tool_id: uuid.UUID
    action: str
    input_summary: dict | None
    output_summary: dict | None
    status: str
    risk_score: int | None
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    error_code: str | None
    cost: float | None
    created_at: datetime


class RuntimeEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    agent_id: uuid.UUID | None
    deployment_id: uuid.UUID | None
    execution_id: uuid.UUID | None
    event_type: str
    severity: str
    payload: dict | None
    created_at: datetime


# --------------------------------------------------------------------------- #
# Capabilities (§18, §19)
# --------------------------------------------------------------------------- #
class CapabilityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    category: str | None = Field(default=None, max_length=50)
    risk_level: str = Field(default="MEDIUM", pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    requires_approval: bool = False
    required_permissions: list[str] = Field(default_factory=list)
    prohibited_environments: list[str] = Field(default_factory=list)


class CapabilityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    display_name: str
    description: str | None
    category: str | None
    risk_level: str
    requires_approval: bool
    required_permissions: list[str]
    prohibited_environments: list[str]
    created_at: datetime
    updated_at: datetime


class AgentCapabilityAssign(BaseModel):
    capability_id: uuid.UUID
    agent_version_id: uuid.UUID | None = None
    constraints: dict | None = None


class AgentCapabilityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    agent_version_id: uuid.UUID | None
    capability_id: uuid.UUID
    status: str
    constraints: dict | None
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


# --------------------------------------------------------------------------- #
# Tools (§20, §23)
# --------------------------------------------------------------------------- #
class ToolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    tool_type: str = Field(default="FUNCTION", max_length=30)
    endpoint_reference: str | None = Field(default=None, max_length=500)
    input_schema: dict | None = None
    output_schema: dict | None = None
    risk_level: str = Field(default="MEDIUM", pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    side_effect_level: str = Field(default="NONE", max_length=20)
    data_classification: str = Field(default="INTERNAL", max_length=30)
    requires_approval: bool = False
    timeout_seconds: int = Field(default=30, ge=1, le=600)


class ToolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None
    name: str
    display_name: str
    description: str | None
    tool_type: str
    endpoint_reference: str | None
    risk_level: str
    side_effect_level: str
    data_classification: str
    requires_approval: bool
    timeout_seconds: int
    enabled: bool
    created_at: datetime
    updated_at: datetime


class AgentToolAssign(BaseModel):
    tool_id: uuid.UUID
    agent_version_id: uuid.UUID | None = None
    allowed_actions: list[str] = Field(default_factory=lambda: ["EXECUTE"])
    constraints: dict | None = None
    environment: str | None = None


class AgentToolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    agent_version_id: uuid.UUID | None
    tool_id: uuid.UUID
    allowed_actions: list[str]
    constraints: dict | None
    environment: str | None
    status: str
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


# --------------------------------------------------------------------------- #
# Runtime approvals (§39)
# --------------------------------------------------------------------------- #
class RuntimeApprovalDecision(BaseModel):
    decision: str = Field(pattern="^(APPROVED|REJECTED)$")
    comment: str | None = None


class RuntimeApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    agent_id: uuid.UUID | None
    agent_version_id: uuid.UUID | None
    deployment_id: uuid.UUID | None
    execution_id: uuid.UUID | None
    requested_action: str
    risk_score: int | None
    reason: str | None
    matched_policies: list
    request_summary: dict | None
    status: str
    requested_by: uuid.UUID | None
    reviewed_by: uuid.UUID | None
    decision_comment: str | None
    expires_at: datetime | None
    created_at: datetime
    reviewed_at: datetime | None


# --------------------------------------------------------------------------- #
# Kill switch (§60)
# --------------------------------------------------------------------------- #
class KillSwitchRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


# --------------------------------------------------------------------------- #
# Dashboard (§70)
# --------------------------------------------------------------------------- #
class RuntimeDashboardRead(BaseModel):
    registered_agents: int
    active_agents: int
    active_deployments: int
    running_executions: int
    queued_executions: int
    failed_executions_24h: int
    pending_approvals: int
    suspended_agents: int
    cost_today: float
    success_rate: float
    avg_queue_ms: float
    avg_execution_ms: float
    execution_trend: list[dict]
    status_distribution: list[dict]
