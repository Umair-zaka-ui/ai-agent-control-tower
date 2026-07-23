"""Agent Runtime & Lifecycle Management models (Phase 5.0 §62).

The existing ``agents`` table (Phase 1/3) already represents the stable
logical agent used throughout authorization and governance; Phase 5 does not
fork a parallel registry. It gains additive runtime-lifecycle columns (see
migration ``0023_agent_runtime``) and everything below hangs off
``agents.id``.

``agent_executions`` doubles as the execution queue (SRS §30: "PostgreSQL
backed queue for development") — a worker claims work with a
``SELECT ... FOR UPDATE SKIP LOCKED`` against ``status = 'QUEUED'`` and takes
a lease row in ``execution_locks`` (§32), so no separate queue table exists.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class AgentDefinition(Base, UUIDPrimaryKeyMixin):
    """§7.2 — behaviour and configuration contract for an agent."""

    __tablename__ = "agent_definitions"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    framework: Mapped[str] = mapped_column(String(50), nullable=False, default="CUSTOM")
    framework_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entrypoint_type: Mapped[str] = mapped_column(String(30), nullable=False, default="FUNCTION")
    entrypoint: Mapped[str] = mapped_column(String(500), nullable=False)
    runtime_language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    system_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    configuration_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    input_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Phase 5.1 SRS §7 requirement declarations — intent, not enforcement;
    # nothing in the runtime resolves these against real infrastructure yet
    # (see docs/runtime/registry/agent-definitions.md).
    capability_declarations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    tool_declarations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    model_requirements: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    memory_requirements: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    data_requirements: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    network_requirements: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    secret_requirements: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    runtime_requirements: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # "metadata" is reserved by SQLAlchemy's declarative base; the DB column
    # keeps the SRS name via `name=`.
    extra_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AgentVersion(Base, UUIDPrimaryKeyMixin):
    """§7.3, §11 — an immutable, checksummed agent version."""

    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_version"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_definitions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    semantic_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.1.0")
    # DRAFT / VALIDATING / READY_FOR_REVIEW / APPROVED / PUBLISHED / DEPRECATED / REVOKED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT", index=True)
    configuration_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    prompt_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    model_configuration: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    capabilities_snapshot: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    tools_snapshot: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    policy_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Phase 5.2.4 — widened from 64 to fit the algorithm-prefixed
    # "sha256:<64 hex>" canonical-sha256 format (71 chars); legacy rows'
    # bare 64-char hex values fit unchanged.
    checksum: Mapped[str] = mapped_column(String(80), nullable=False)
    release_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Phase 5.2 Part 1 (SRS 5.2 §7-8, §17-25) — release-management foundation.
    # Compatibility *analysis* (§30) and real cryptographic signing are out of
    # scope for this part (deferred to Part 3 / a future signing phase); these
    # columns exist as the storage foundation those parts will populate.
    release_channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_release_channels.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    compatibility_level: Mapped[str] = mapped_column(String(20), nullable=False, default="UNKNOWN")
    signature_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    snapshot_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    rollback_target_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="SET NULL"), nullable=True,
    )
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="SET NULL"), nullable=True,
    )
    release_branch: Mapped[str] = mapped_column(String(100), nullable=False, default="main")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Phase 5.2.6 — which baseline `compatibility_level` was computed against,
    # and when (see app/runtime/versioning/compatibility.py).
    compatibility_baseline_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    compatibility_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Phase 5.2.4 — signing & provenance (ACT-VER-FR-060..071).
    checksum_algorithm: Mapped[str] = mapped_column(String(20), nullable=False, default="canonical-sha256")
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    manifest_digest: Mapped[str | None] = mapped_column(String(80), nullable=True)


class AgentReleaseChannel(Base, UUIDPrimaryKeyMixin):
    """Phase 5.2 Part 1 §9, §26 — global release-channel catalog (STABLE,
    BETA, CANARY, INTERNAL, seeded by migration 0025)."""

    __tablename__ = "agent_release_channels"

    name: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentVersionSnapshot(Base, UUIDPrimaryKeyMixin):
    """Phase 5.2 Part 1 §10-14 — the complete frozen snapshot document for one
    version (registry metadata + definition + release metadata + everything),
    one row per version. Never updated once created — a new version gets a
    new snapshot row, never a mutated one."""

    __tablename__ = "agent_version_snapshots"

    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Phase 5.2.4 — widened from 64 to fit "sha256:<64 hex>" (71 chars).
    checksum: Mapped[str] = mapped_column(String(80), nullable=False)
    checksum_algorithm: Mapped[str] = mapped_column(String(20), nullable=False, default="canonical-sha256")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentReleaseMetadata(Base, UUIDPrimaryKeyMixin):
    """Phase 5.2 Part 1 §26, §28 — release naming, justification and window,
    one row per version."""

    __tablename__ = "agent_release_metadata"

    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    release_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    release_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    # MAJOR / MINOR / PATCH / HOTFIX
    change_category: Mapped[str | None] = mapped_column(String(20), nullable=True)
    release_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    support_end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_ticket: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    commit_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    build_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    documentation_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AgentReleaseArtifact(Base, UUIDPrimaryKeyMixin):
    """Phase 5.2 Part 1 §27 — an artifact reference attached to a version
    (OCI image digest, git commit SHA, build pipeline ID, model/prompt
    package identifier, config bundle, SBOM or signature reference). Many
    per version; references only — no binaries are embedded or stored here."""

    __tablename__ = "agent_release_artifacts"

    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # OCI_IMAGE_DIGEST / GIT_COMMIT_SHA / BUILD_PIPELINE_ID / MODEL_PACKAGE /
    # PROMPT_PACKAGE / CONFIG_BUNDLE / SBOM_REFERENCE / SIGNATURE_REFERENCE
    artifact_type: Mapped[str] = mapped_column(String(30), nullable=False)
    reference: Mapped[str] = mapped_column(String(500), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentReleaseNote(Base, UUIDPrimaryKeyMixin):
    """Phase 5.2 Part 1 §28 — one structured, categorized release-note entry.
    Distinct from ``AgentVersion.release_notes`` (a free-text summary field);
    many of these per version."""

    __tablename__ = "agent_release_notes"

    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # ADDED / CHANGED / FIXED / REMOVED / SECURITY / DEPRECATED
    category: Mapped[str] = mapped_column(String(20), nullable=False, default="CHANGED")
    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentVersionStatusHistory(Base, UUIDPrimaryKeyMixin):
    """Phase 5.2 Part 1 §19, §25 — an immutable ledger of every lifecycle
    transition a version goes through, mirroring ``AgentLifecycleEvent`` for
    the registry (Phase 5.1)."""

    __tablename__ = "agent_version_status_history"

    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    previous_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    new_status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentVersionCompatibilityFinding(Base, UUIDPrimaryKeyMixin):
    """Phase 5.2.6 SRS ACT-VER-FR-100..108 — one detected change between a
    version and its resolved baseline (see
    app/runtime/versioning/compatibility.py). Many per version; replaced
    wholesale (not accumulated) each time analysis re-runs for that version."""

    __tablename__ = "agent_version_compatibility_findings"

    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    baseline_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="SET NULL"), nullable=True,
    )
    # INPUT_CONTRACT / OUTPUT_CONTRACT / TOOL_BINDING / CAPABILITY / MODEL_CONFIG /
    # RESOURCE_LIMIT / POLICY / PROMPT / METADATA
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    # ADDED / REMOVED / MODIFIED
    change_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # BREAKING / BACKWARD_COMPATIBLE / COMPATIBLE
    materiality: Mapped[str] = mapped_column(String(20), nullable=False)
    baseline_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    candidate_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SigningKey(Base, UUIDPrimaryKeyMixin):
    """Phase 5.2.4 SRS ACT-VER-FR-060..071 — the DB record of a signing
    key's *identity and current public material* — never private key
    material (see ``app/runtime/versioning/signing/base.py``'s
    ``SigningProvider`` contract). One row per logical ``key_id``; rotation
    bumps ``current_version`` and adds a ``SigningKeyVersion`` row rather
    than replacing this one."""

    __tablename__ = "signing_keys"

    key_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    # LOCAL / AZURE_KEY_VAULT
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="LOCAL")
    # ED25519 / ECDSA_P256_SHA256
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False, default="ED25519")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # ACTIVE / ROTATED / REVOKED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    public_key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SigningKeyVersion(Base, UUIDPrimaryKeyMixin):
    """Phase 5.2.4 — historical public keys, so a signature made with a
    rotated-out key version stays verifiable forever (``retired_at`` is
    informational only; the row and its public key are never deleted)."""

    __tablename__ = "signing_key_versions"
    __table_args__ = (
        UniqueConstraint("signing_key_id", "version", name="uq_signing_key_versions_key_version"),
    )

    signing_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("signing_keys.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    public_key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentVersionSignature(Base, UUIDPrimaryKeyMixin):
    """Phase 5.2.4 SRS ACT-VER-FR-060..071 — one signature over a version's
    manifest digest. Multiple rows per version are permitted
    (``ACT-VER-FR-069``) — the automatic ``PUBLISHER`` signature made at
    publish time, plus any number of later ``COUNTERSIGN`` rows. Revoking
    the signing key updates ``verification_status`` here; it never alters
    ``signature`` or the version row (``ACT-VER-FR-066``) — the historical
    fact that it was signed remains true, only its current trust status
    changes."""

    __tablename__ = "agent_version_signatures"

    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    manifest_digest: Mapped[str] = mapped_column(String(80), nullable=False)
    signature: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False)
    signing_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("signing_keys.id", ondelete="RESTRICT"), nullable=False,
    )
    signing_key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # PUBLISHER / COUNTERSIGN
    signature_type: Mapped[str] = mapped_column(String(32), nullable=False, default="PUBLISHER")
    dsse_envelope: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # VALID / INVALID / KEY_REVOKED / UNVERIFIED
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False, default="UNVERIFIED")
    signed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    signed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )


class AgentVersionProvenance(Base, UUIDPrimaryKeyMixin):
    """Phase 5.2.4 SRS ACT-VER-FR-060..071 — who/what/where produced a
    version, one row per version. Distinct from ``AgentVersionSignature``
    (the cryptographic proof) — this is the human-readable provenance
    record the attestation's ``predicate.provenance`` section is built
    from."""

    __tablename__ = "agent_version_provenance"

    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False, default="USER")
    source_repository: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    build_environment: Mapped[str | None] = mapped_column(String(128), nullable=True)
    builder_identity: Mapped[str] = mapped_column(Text, nullable=False)
    source_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    attestation_document: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentDeployment(Base, UUIDPrimaryKeyMixin):
    """§7.4, §14 — one agent version deployed into one environment."""

    __tablename__ = "agent_deployments"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    environment: Mapped[str] = mapped_column(String(20), nullable=False, default="DEVELOPMENT")
    deployment_strategy: Mapped[str] = mapped_column(String(20), nullable=False, default="RECREATE")
    # CREATED / PENDING_APPROVAL / SCHEDULED / DEPLOYING / HEALTH_CHECKING /
    # ACTIVE / DEGRADED / FAILED / SUSPENDED / ROLLING_BACK / RETIRED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="CREATED", index=True)
    desired_replicas: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active_replicas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    configuration: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    secret_references: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    runtime_limits: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    health_status: Mapped[str] = mapped_column(String(20), nullable=False, default="UNKNOWN")
    deployed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentExecution(Base, UUIDPrimaryKeyMixin):
    """§7.5, §27 — one runtime invocation and its queue/state-machine record."""

    __tablename__ = "agent_executions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    deployment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_deployments.id", ondelete="SET NULL"), nullable=True
    )
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False, default="API")
    triggered_by_identity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    parent_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_executions.id", ondelete="SET NULL"), nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    input_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # CREATED / AUTHORIZING / DENIED / PENDING_APPROVAL / REJECTED / QUEUED /
    # SCHEDULED / RUNNING / WAITING_FOR_TOOL / WAITING_FOR_APPROVAL / RETRYING /
    # SUCCEEDED / FAILED / TIMED_OUT / CANCELLED / BLOCKED / SUSPENDED / DEAD_LETTERED
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="CREATED", index=True)
    decision: Mapped[str | None] = mapped_column(String(24), nullable=True)
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="NORMAL")
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tool_usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cost: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ExecutionAttempt(Base, UUIDPrimaryKeyMixin):
    """§31 — one worker's attempt at running an execution (retry history)."""

    __tablename__ = "execution_attempts"

    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_executions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RUNNING")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExecutionLock(Base, UUIDPrimaryKeyMixin):
    """§32 — a lease preventing duplicate concurrent execution of one job."""

    __tablename__ = "execution_locks"

    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_executions.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    worker_id: Mapped[str] = mapped_column(String(100), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Capability(Base, UUIDPrimaryKeyMixin):
    """§18 — a declared, potential behaviour an agent may be assigned."""

    __tablename__ = "capabilities"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM")
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    required_permissions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    prohibited_environments: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AgentCapability(Base, UUIDPrimaryKeyMixin):
    """§19 — a capability assignment on one agent (version)."""

    __tablename__ = "agent_capabilities"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="CASCADE"), nullable=True
    )
    capability_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("capabilities.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # REQUESTED / APPROVED / DENIED / REVOKED / EXPIRED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="REQUESTED", index=True)
    constraints: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Tool(Base, UUIDPrimaryKeyMixin):
    """§20 — a callable function or external system available to agents."""

    __tablename__ = "tools"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_type: Mapped[str] = mapped_column(String(30), nullable=False, default="FUNCTION")
    endpoint_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    input_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM")
    side_effect_level: Mapped[str] = mapped_column(String(20), nullable=False, default="NONE")
    data_classification: Mapped[str] = mapped_column(String(30), nullable=False, default="INTERNAL")
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AgentTool(Base, UUIDPrimaryKeyMixin):
    """§23 — a tool assignment on one agent (version), with constraints."""

    __tablename__ = "agent_tools"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="CASCADE"), nullable=True
    )
    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    allowed_actions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    constraints: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    environment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="REQUESTED", index=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ToolCall(Base, UUIDPrimaryKeyMixin):
    """§44 — one tool invocation record inside an execution."""

    __tablename__ = "tool_calls"

    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_executions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tools.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    input_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ALLOWED")
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    authorization_decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cost: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RuntimeEvent(Base, UUIDPrimaryKeyMixin):
    """§51, §76 — a runtime lifecycle event (deployment/execution/health)."""

    __tablename__ = "runtime_events"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    deployment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_deployments.id", ondelete="CASCADE"), nullable=True
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_executions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="INFO")
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DeploymentHealth(Base, UUIDPrimaryKeyMixin):
    """§49, §50 — a health/heartbeat sample for a deployment."""

    __tablename__ = "deployment_health"

    deployment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_deployments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="UNKNOWN")
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IdempotencyRecord(Base, UUIDPrimaryKeyMixin):
    """§33 — dedupes execution requests sharing an idempotency key."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("organization_id", "agent_id", "idempotency_key", name="uq_idempotency_key"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    identity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(150), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_executions.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RuntimeApproval(Base, UUIDPrimaryKeyMixin):
    """§39 — a human approval obligation raised by the runtime (deployment,
    version publish, high-risk capability/tool, production execution, …)."""

    __tablename__ = "runtime_approvals"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="CASCADE"), nullable=True
    )
    deployment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_deployments.id", ondelete="CASCADE"), nullable=True
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_executions.id", ondelete="CASCADE"), nullable=True
    )
    # DEPLOYMENT / VERSION_PUBLISH / CAPABILITY_GRANT / TOOL_GRANT / EXECUTION /
    # ROLLBACK / SUSPENSION_OVERRIDE / POLICY_EXCEPTION
    requested_action: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_policies: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    request_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # PENDING / APPROVED / REJECTED / EXPIRED / CANCELLED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decision_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
