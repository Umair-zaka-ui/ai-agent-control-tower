"""Pydantic schemas for the Phase 5.1 Enterprise Agent Registry (SRS 5.1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

_AUTONOMY = Field(default="ASSISTIVE",
                  pattern="^(ASSISTIVE|SUPERVISED|SEMI_AUTONOMOUS|AUTONOMOUS|CRITICAL_AUTONOMOUS)$")
_OWNER_TYPE = Field(pattern="^(USER|TEAM|DEPARTMENT|PROJECT|SERVICE_OWNER_GROUP)$")
_OWNER_ROLE = Field(pattern="^(BUSINESS_OWNER|TECHNICAL_OWNER|COMPLIANCE_OWNER|SECURITY_OWNER|DATA_OWNER)$")


# --------------------------------------------------------------------------- #
# Registration wizard (SRS §22, §23) — one payload covering all 10 steps'
# fields; the frontend enforces the step-by-step UX, the backend validates
# completeness as a whole via AgentValidationService (registry/validation.py).
# --------------------------------------------------------------------------- #
class AgentDefinitionRegistryCreate(BaseModel):
    """Step 5/6 — technical definition + contracts."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    framework: str = Field(default="CUSTOM", max_length=50)
    framework_version: str | None = Field(default=None, max_length=50)
    entrypoint_type: str = Field(default="FUNCTION", max_length=30)
    entrypoint: str = Field(min_length=1, max_length=500)
    runtime_language: str | None = Field(default=None, max_length=50)
    system_instructions: str | None = None
    configuration_schema: dict = Field(default_factory=dict)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    capability_declarations: list[str] = Field(default_factory=list)
    tool_declarations: list[str] = Field(default_factory=list)
    model_requirements: dict = Field(default_factory=dict)
    memory_requirements: dict = Field(default_factory=dict)
    data_requirements: dict = Field(default_factory=dict)
    network_requirements: dict = Field(default_factory=dict)
    secret_requirements: dict = Field(default_factory=dict)
    runtime_requirements: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


class AgentRegistrationCreate(BaseModel):
    # Step 1 — basic information
    name: str = Field(min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    business_purpose: str | None = None
    agent_type: str = Field(default="ASSISTANT", max_length=100)
    tags: list[str] = Field(default_factory=list)
    external_reference: str | None = Field(default=None, max_length=255)
    documentation_url: str | None = Field(default=None, max_length=500)
    repository_url: str | None = Field(default=None, max_length=500)

    # Step 2 — organizational placement
    project_id: uuid.UUID | None = None
    business_unit_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None

    # Step 3 — ownership
    owner_type: str | None = Field(default=None, max_length=30)
    owner_id: uuid.UUID | None = None
    technical_owner_id: uuid.UUID | None = None
    compliance_owner_id: uuid.UUID | None = None
    support_contact: str | None = Field(default=None, max_length=255)

    # Step 4 — machine identity (associate an existing eligible identity;
    # "create a new one" is a separate call, POST .../identity/create-and-associate)
    identity_id: uuid.UUID | None = None

    # Step 5/6 — technical definition + contracts
    definition: AgentDefinitionRegistryCreate

    # Step 7 — data, risk, autonomy
    criticality: str = Field(default="MEDIUM", pattern="^(LOW|MEDIUM|HIGH|MISSION_CRITICAL)$")
    risk_level: str = Field(default="LOW", pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    data_classification: str = Field(default="INTERNAL",
                                     pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED|REGULATED)$")
    autonomy_level: str = _AUTONOMY
    default_environment: str = Field(default="DEVELOPMENT", max_length=20)

    metadata: dict = Field(default_factory=dict)


class AgentRegistryUpdate(BaseModel):
    """A draft-stage edit. ``row_version`` is required (SRS §53) — a mismatch
    against the stored value raises ``AGENT_CONCURRENT_MODIFICATION``."""

    row_version: int
    name: str | None = Field(default=None, min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    business_purpose: str | None = None
    tags: list[str] | None = None
    external_reference: str | None = Field(default=None, max_length=255)
    documentation_url: str | None = Field(default=None, max_length=500)
    repository_url: str | None = Field(default=None, max_length=500)
    project_id: uuid.UUID | None = None
    business_unit_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    owner_type: str | None = Field(default=None, max_length=30)
    owner_id: uuid.UUID | None = None
    technical_owner_id: uuid.UUID | None = None
    compliance_owner_id: uuid.UUID | None = None
    support_contact: str | None = Field(default=None, max_length=255)
    criticality: str | None = Field(default=None, pattern="^(LOW|MEDIUM|HIGH|MISSION_CRITICAL)$")
    risk_level: str | None = Field(default=None, pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    data_classification: str | None = Field(
        default=None, pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED|REGULATED)$")
    autonomy_level: str | None = Field(
        default=None, pattern="^(ASSISTIVE|SUPERVISED|SEMI_AUTONOMOUS|AUTONOMOUS|CRITICAL_AUTONOMOUS)$")
    default_environment: str | None = Field(default=None, max_length=20)
    metadata: dict | None = None


class AgentRegistryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    display_name: str | None
    slug: str | None
    description: str | None
    business_purpose: str | None
    agent_type: str
    status: str
    lifecycle_status: str
    criticality: str
    risk_level: str
    data_classification: str
    autonomy_level: str
    default_environment: str
    project_id: uuid.UUID | None
    business_unit_id: uuid.UUID | None
    department_id: uuid.UUID | None
    team_id: uuid.UUID | None
    identity_id: uuid.UUID | None
    owner_type: str | None
    owner_id: uuid.UUID | None
    technical_owner_id: uuid.UUID | None
    compliance_owner_id: uuid.UUID | None
    support_contact: str | None
    documentation_url: str | None
    repository_url: str | None
    tags: list[str]
    metadata: dict = Field(validation_alias="extra_metadata")
    registration_source: str
    external_reference: str | None
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None
    row_version: int
    created_at: datetime
    updated_at: datetime
    validated_at: datetime | None
    approved_at: datetime | None
    activated_at: datetime | None
    suspended_at: datetime | None
    archived_at: datetime | None
    retired_at: datetime | None


class AgentLifecycleActionRequest(BaseModel):
    """Body for POST .../{action} lifecycle-transition endpoints (submit,
    approve, reject, activate, suspend, resume, deprecate, archive, restore,
    retire) — every transition may carry a reason; rejection requires one."""

    reason: str | None = None


# --------------------------------------------------------------------------- #
# Ownership (SRS §12, §13)
# --------------------------------------------------------------------------- #
class OwnershipTransferRequest(BaseModel):
    owner_role: str = _OWNER_ROLE
    new_owner_type: str = _OWNER_TYPE
    new_owner_id: uuid.UUID
    reason: str = Field(min_length=1)


class OwnershipHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    owner_role: str
    previous_owner_type: str | None
    previous_owner_id: uuid.UUID | None
    new_owner_type: str
    new_owner_id: uuid.UUID
    reason: str
    changed_by: uuid.UUID
    approved_by: uuid.UUID | None
    changed_at: datetime


class AgentOwnershipRead(BaseModel):
    """Current ownership snapshot — GET .../{agentId}/ownership."""

    owner_type: str | None
    owner_id: uuid.UUID | None
    technical_owner_id: uuid.UUID | None
    compliance_owner_id: uuid.UUID | None


# --------------------------------------------------------------------------- #
# Machine identity (SRS §11)
# --------------------------------------------------------------------------- #
class IdentityAssociateRequest(BaseModel):
    identity_id: uuid.UUID


class IdentityCreateAndAssociateRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=100)
    credential_type: str = Field(default="API_KEY", max_length=30)
    expires_at: datetime | None = None


class IdentityReplaceRequest(BaseModel):
    """Rotates the agent's current identity credential in place (§11.1's
    one-identity-per-agent constraint means 'replace' can't mean pointing at
    a second pre-existing row — there can never be one). The identity's
    ``id`` is unchanged; ``client_id``/``credential_type``/``expires_at`` are
    updated on the same row."""

    client_id: str = Field(min_length=1, max_length=100)
    credential_type: str = Field(default="API_KEY", max_length=30)
    expires_at: datetime | None = None
    reason: str = Field(min_length=1)


class AgentIdentityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    client_id: str
    credential_type: str
    status: str
    last_used_at: datetime | None
    expires_at: datetime | None


# --------------------------------------------------------------------------- #
# Validation (SRS §25, §26, §27, §30)
# --------------------------------------------------------------------------- #
class ValidationFinding(BaseModel):
    code: str
    field: str | None = None
    message: str
    severity: str  # INFO / WARNING / ERROR / BLOCKING


class ValidationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    status: str
    validator_version: str
    summary: dict
    errors: list[dict]
    warnings: list[dict]
    checks: list[dict]
    started_at: datetime
    completed_at: datetime | None
    created_by: uuid.UUID | None
    created_at: datetime


class SchemaTestRequest(BaseModel):
    schema_type: str = Field(pattern="^(INPUT|OUTPUT|CONFIGURATION)$")
    payload: dict = Field(default_factory=dict)


class SchemaTestResponse(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Duplicate detection (SRS §32, §33, §64)
# --------------------------------------------------------------------------- #
class DuplicateMatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_agent_id: uuid.UUID
    candidate_agent_id: uuid.UUID
    match_type: str
    confidence_score: Decimal
    matching_fields: list[str]
    status: str
    reviewed_by: uuid.UUID | None
    review_decision: str | None
    review_reason: str | None
    created_at: datetime
    reviewed_at: datetime | None


class DuplicateReviewRequest(BaseModel):
    review_decision: str = Field(
        pattern="^(CONFIRM_DUPLICATE|NOT_DUPLICATE|MERGE_REQUIRED|JUSTIFIED_SEPARATE_AGENT)$")
    review_reason: str = Field(min_length=1)


# --------------------------------------------------------------------------- #
# Import / export (SRS §39-§45)
# --------------------------------------------------------------------------- #
class ImportRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    format: str = Field(pattern="^(JSON|YAML|CSV)$")
    mode: str = Field(pattern="^(CREATE_ONLY|UPDATE_DRAFTS|UPSERT_NON_ACTIVE|VALIDATE_ONLY)$")
    content: str = Field(min_length=1, description="Raw file content (JSON/YAML text or CSV text).")


class ImportItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    import_job_id: uuid.UUID
    record_identifier: str
    status: str
    agent_id: uuid.UUID | None
    errors: list[dict]
    warnings: list[dict]
    created_at: datetime


class ImportJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    file_name: str
    format: str
    mode: str
    status: str
    total_records: int
    successful_records: int
    failed_records: int
    warning_records: int
    created_by: uuid.UUID | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class ExportRequest(BaseModel):
    export_type: str = Field(
        pattern="^(FULL_CONFIGURATION|INVENTORY_SUMMARY|COMPLIANCE_REPORT|MIGRATION_PACKAGE)$")
    format: str = Field(pattern="^(JSON|YAML|CSV)$")
    filters: dict = Field(default_factory=dict)


class ExportJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    export_type: str
    format: str
    filters: dict
    status: str
    record_count: int
    storage_reference: str | None
    expires_at: datetime | None
    created_by: uuid.UUID | None
    created_at: datetime
    completed_at: datetime | None


# --------------------------------------------------------------------------- #
# Legacy migration (SRS §70-§73)
# --------------------------------------------------------------------------- #
class AgentLifecycleEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    organization_id: uuid.UUID
    previous_status: str | None
    new_status: str
    reason: str | None
    requested_by: uuid.UUID
    approved_by: uuid.UUID | None
    authorization_decision_id: uuid.UUID | None
    request_id: str
    correlation_id: str
    metadata: dict = Field(validation_alias="extra_metadata")
    created_at: datetime


class MigrationRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    migration_batch_id: str
    legacy_source: str
    legacy_id: str
    migration_status: str
    mapping_warnings: list[str]
    migrated_by: uuid.UUID | None
    migrated_at: datetime
