"""Pydantic schemas for the Phase 5.2 Part 1 versioning foundation."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.runtime.versioning.artifacts import ARTIFACT_TYPES
from app.runtime.versioning.notes import NOTE_CATEGORIES

_ARTIFACT_TYPE = Field(pattern="^(" + "|".join(ARTIFACT_TYPES) + ")$")
_NOTE_CATEGORY = Field(default="CHANGED", pattern="^(" + "|".join(NOTE_CATEGORIES) + ")$")


class ReleaseChannelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    is_default: bool
    created_at: datetime


class VersionSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_version_id: uuid.UUID
    snapshot: dict
    checksum: str
    created_at: datetime


class ReleaseMetadataUpsert(BaseModel):
    release_name: str | None = Field(default=None, max_length=255)
    release_description: str | None = None
    business_justification: str | None = None
    change_category: str | None = Field(default=None, pattern="^(MAJOR|MINOR|PATCH|HOTFIX)$")
    release_window_start: datetime | None = None
    release_window_end: datetime | None = None
    support_end_date: datetime | None = None
    approval_ticket: str | None = Field(default=None, max_length=100)
    source_branch: str | None = Field(default=None, max_length=200)
    commit_reference: str | None = Field(default=None, max_length=100)
    build_reference: str | None = Field(default=None, max_length=200)
    risk_score: int | None = Field(default=None, ge=0, le=100)
    documentation_url: str | None = Field(default=None, max_length=500)


class ReleaseMetadataRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_version_id: uuid.UUID
    release_name: str | None
    release_description: str | None
    business_justification: str | None
    change_category: str | None
    release_window_start: datetime | None
    release_window_end: datetime | None
    support_end_date: datetime | None
    approval_ticket: str | None
    source_branch: str | None
    commit_reference: str | None
    build_reference: str | None
    risk_score: int | None
    documentation_url: str | None
    created_at: datetime
    updated_at: datetime


class ReleaseArtifactCreate(BaseModel):
    artifact_type: str = _ARTIFACT_TYPE
    reference: str = Field(min_length=1, max_length=500)


class ReleaseArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_version_id: uuid.UUID
    artifact_type: str
    reference: str
    created_by: uuid.UUID | None
    created_at: datetime


class ReleaseNoteCreate(BaseModel):
    category: str = _NOTE_CATEGORY
    note: str = Field(min_length=1)


class ReleaseNoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_version_id: uuid.UUID
    category: str
    note: str
    created_by: uuid.UUID | None
    created_at: datetime


class VersionStatusHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_version_id: uuid.UUID
    previous_status: str | None
    new_status: str
    reason: str | None
    changed_by: uuid.UUID | None
    created_at: datetime


class RollbackTargetRequest(BaseModel):
    target_version_id: uuid.UUID


class RevokeVersionRequest(BaseModel):
    reason: str | None = None


class VersionComparisonRead(BaseModel):
    version_a: dict
    version_b: dict
    scalar_changes: dict
    configuration_changes: dict
    list_changes: dict
    artifacts_added: list[dict]
    artifacts_removed: list[dict]
    notes_added: list[dict]
    notes_removed: list[dict]
    identical: bool


class ReadinessCheckRead(BaseModel):
    name: str
    passed: bool
    message: str
    skipped: bool = False


class VersionReadinessRead(BaseModel):
    ready: bool
    checks: list[ReadinessCheckRead]


# --------------------------------------------------------------------------- #
# Compatibility & breaking-change detection (Phase 5.2.6)
# --------------------------------------------------------------------------- #
class CompatibilityFindingRead(BaseModel):
    """A persisted finding row — used by the standalone findings-list endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_version_id: uuid.UUID
    baseline_version_id: uuid.UUID | None
    category: str
    path: str
    change_type: str
    materiality: str
    baseline_value: str | None
    candidate_value: str | None
    description: str
    created_at: datetime


class CompatibilityReportFinding(BaseModel):
    """A finding as embedded in a compatibility report (§4.5) — no id/
    timestamps, since an ephemeral (unpersisted) report has neither."""

    category: str
    path: str
    change_type: str
    materiality: str
    baseline_value: str | None
    candidate_value: str | None
    description: str


class CompatibilitySummary(BaseModel):
    breaking: int
    backward_compatible: int
    compatible: int


class CompatibilityReportRead(BaseModel):
    candidate_version_id: uuid.UUID
    baseline_version_id: uuid.UUID | None
    compatibility_level: str
    declared_semver: str
    declared_increment: str | None
    expected_increment: str | None
    semver_consistent: bool
    analyzed_at: datetime | None
    summary: CompatibilitySummary
    findings: list[CompatibilityReportFinding]


# --------------------------------------------------------------------------- #
# Cryptographic signing, provenance & attestation (Phase 5.2.4)
# --------------------------------------------------------------------------- #
class SignatureRead(BaseModel):
    """Signature metadata only — never the raw signature bytes or the full
    DSSE envelope (see ``AttestationRead`` for that)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_version_id: uuid.UUID
    manifest_digest: str
    algorithm: str
    signing_key_id: uuid.UUID
    signing_key_version: int
    signature_type: str
    verification_status: str
    signed_at: datetime
    signed_by: uuid.UUID | None


class ProvenanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_version_id: uuid.UUID
    actor_id: uuid.UUID
    actor_type: str
    source_repository: str | None
    source_commit: str | None
    source_ref: str | None
    build_environment: str | None
    builder_identity: str
    source_ip: str | None
    correlation_id: uuid.UUID | None
    created_at: datetime


class AttestationRead(BaseModel):
    """The in-toto Statement v1 document plus its DSSE envelope, for the
    primary (``PUBLISHER``) signature — ``GET .../attestation``."""

    document: dict
    dsse_envelope: dict


class SigningKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key_id: str
    provider: str
    algorithm: str
    current_version: int
    status: str
    public_key_pem: str
    revoked_at: datetime | None
    revocation_reason: str | None
    created_at: datetime
    updated_at: datetime


class RevokeSigningKeyRequest(BaseModel):
    reason: str | None = None


class SignatureVerificationCheck(BaseModel):
    signature_id: uuid.UUID
    signature_type: str
    passed: bool
    signature_valid: bool
    key_revoked: bool


class VerificationResultRead(BaseModel):
    version_id: uuid.UUID
    valid: bool
    snapshot_intact: bool
    signatures: list[SignatureVerificationCheck]
