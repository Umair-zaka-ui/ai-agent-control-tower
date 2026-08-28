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
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
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

    # Phase 3.1 (ACT-SRS-M3 §3.1) -- the new governed lifecycle. Deliberately a
    # *second* status field, not a widening of ``status`` above: ``status`` is
    # the pre-existing, narrower Phase 5.0 field every legacy DeploymentService
    # method (deploy/suspend/resume/rollback/retire) still reads and writes
    # unchanged; ``lifecycle_state`` is the new 15-state machine and is written
    # in exactly one place, ``app.runtime.deployment.service.DeploymentLifecycleService``
    # (see that module for the full transition graph). The two fields are
    # reconciled once, deterministically, by migration 0037's own mapping and
    # then evolve independently -- see docs/deployment/lifecycle.md.
    lifecycle_state: Mapped[str] = mapped_column(String(24), nullable=False, default="DRAFT", index=True)
    # Optimistic-concurrency guard (``version_id_col`` below) -- SQLAlchemy
    # includes ``WHERE revision = <loaded value>`` on every UPDATE of this row
    # and raises ``StaleDataError`` (translated to ``DEPLOYMENT_REVISION_CONFLICT``
    # by the lifecycle service) when a concurrent writer already moved it,
    # rather than silently last-write-winning.
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    superseded_by_deployment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_deployments.id", ondelete="SET NULL"), nullable=True
    )

    # Phase 3.2 (ACT-SRS-M3 §3.2) -- the governed environment entity this
    # deployment targets. Additive, nullable: the pre-existing ``environment``
    # string column above is left in place unchanged (every legacy read --
    # in particular the M1 execution-path check in
    # ``RuntimePolicyService.evaluate`` -- keeps reading that string, never
    # this column), and migration 0038 backfills this column for every
    # existing row from that same string. New rows created through
    # ``app.runtime.environment.service.PromotionService`` always set both
    # columns together, in sync; the legacy ``POST /deployments`` create path
    # additionally does a best-effort string->row lookup on create,
    # opportunistically closing the loop for orgs whose environments are
    # already seeded (see docs/deployment/environments.md).
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("environments.id", ondelete="SET NULL"), nullable=True, index=True,
    )

    __mapper_args__ = {"version_id_col": revision}


class Environment(Base, UUIDPrimaryKeyMixin):
    """Phase 3.2 (ACT-SRS-M3 §3.2, M3-3.2-FR-001..004) -- a governed,
    tenant-scoped deployment target (DEVELOPMENT/TEST/STAGING/PRODUCTION/
    SANDBOX, or an org-defined custom name). Turns ``agent_deployments.
    environment`` from a bare, unvalidated string into a first-class,
    policy-bearing entity -- see ``app.runtime.environment`` and
    docs/deployment/environments.md.

    ``policy`` (free-form JSONB, evaluated by ``app.runtime.environment.
    policy``) may declare ``allowed_models``, ``allowed_data_classifications``,
    ``requires_approval``, ``maximum_concurrent_deployments`` and
    ``change_window`` -- see that module's own docstring for the exact shape
    and which of these are actually enforced this phase versus only modeled.
    Never holds a secret (FR rule shared with every other policy JSONB in
    this codebase)."""

    __tablename__ = "environments"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_environments_org_name"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_production: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    policy: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PromotionPath(Base, UUIDPrimaryKeyMixin):
    """Phase 3.2 (ACT-SRS-M3 §3.2, M3-3.2-FR-020..021) -- one org-configured,
    directed edge between two ``Environment`` rows a version's deployment
    eligibility may be promoted along (e.g. STAGING -> PRODUCTION).
    Promoting between two environments with no row here is rejected
    (``PROMOTION_PATH_NOT_DEFINED``) -- see ``app.runtime.environment.service.
    PromotionService``."""

    __tablename__ = "promotion_paths"
    __table_args__ = (
        UniqueConstraint("organization_id", "from_environment_id", "to_environment_id",
                        name="uq_promotion_paths_org_edge"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    from_environment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("environments.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    to_environment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("environments.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DeploymentPreflightResult(Base, UUIDPrimaryKeyMixin):
    """Phase 3.3 (ACT-SRS-M3 §Phase-3.3, M3-3.3-FR-030..031) -- one persisted
    ``ReleaseGateService.evaluate()`` verdict for a deployment. A snapshot,
    not a queryable-by-finding entity: ``findings`` is a JSONB list of
    ``{code, severity, source, explanation, remediation}`` objects (see
    ``app.runtime.deployment.gate``), not normalized into rows, because a
    finding only ever matters in the context of the one evaluation that
    produced it -- see docs/deployment/release-gates.md."""

    __tablename__ = "deployment_preflight_results"

    deployment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_deployments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    verdict: Mapped[str] = mapped_column(String(12), nullable=False)
    findings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    evaluated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        Index("ix_deployment_preflight_results_deployment_evaluated",
             "deployment_id", "evaluated_at"),
    )


class DeploymentTrafficAllocation(Base, UUIDPrimaryKeyMixin):
    """Phase 3.4 (ACT-SRS-M3 §Phase-3.4, M3-3.4-FR-001..005) -- one revision of
    the weighted split of an agent's traffic across simultaneously-serving
    versions, in one environment.

    A *sanctioned new domain object* (ruling #2): traffic allocation is not a
    property of any single deployment -- it spans several of them -- so it
    cannot live as columns on ``agent_deployments`` without one deployment
    row arbitrarily owning the others' weights. It hangs off
    ``(organization, agent, environment)`` instead, exactly the tuple the
    resolver looks up on every gated execution.

    **Revisions, not mutations.** A weight change never updates an existing
    row: it writes a new allocation (``revision = previous + 1``,
    ``is_current = True``) and clears ``is_current`` on the previous one, both
    inside one transaction. Prior revisions are retained forever as the
    auditable "who changed weights to what, when" lineage (FR-004), and the
    partial-unique index on ``is_current`` (see migration 0040) is what makes
    two concurrent writers unable to both win -- the loser's INSERT violates
    the index and is translated to ``TRAFFIC_ALLOCATION_CONFLICT``. That
    index, not an advisory lock, is this domain's concurrency primitive --
    the same "let Postgres be the arbiter" discipline
    ``app.runtime.deployment.idempotency`` already established, and
    deliberately lock-free so the resolver can never deadlock against the
    execution path's own locks (§9, the Milestone 1 lesson).

    The weights-sum-to-100 invariant (FR-001) is enforced at write time in
    ``app.runtime.deployment.traffic``, inside the same transaction that
    inserts the rows, so a partial or non-100 set is never committed and
    therefore never observable (FR-003)."""

    __tablename__ = "deployment_traffic_allocations"
    __table_args__ = (
        Index("ix_traffic_allocations_agent_environment_current",
             "agent_id", "environment_id", "is_current"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    environment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("environments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class DeploymentTrafficWeight(Base, UUIDPrimaryKeyMixin):
    """Phase 3.4 -- one (version, deployment, weight) entry of one allocation
    revision. ``deployment_id`` records which active deployment serves this
    version: the resolver re-checks *that* deployment's servability at
    resolution time, so a weight pointing at a deployment paused or
    superseded after the weights were set simply stops being routed to,
    without any allocation rewrite (M3-3.4-FR-022)."""

    __tablename__ = "deployment_traffic_weights"
    __table_args__ = (
        UniqueConstraint("allocation_id", "agent_version_id",
                        name="uq_traffic_weights_allocation_version"),
        CheckConstraint("weight >= 0 AND weight <= 100", name="ck_traffic_weights_range"),
        Index("ix_traffic_weights_allocation_id", "allocation_id"),
    )

    allocation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deployment_traffic_allocations.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    deployment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_deployments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    weight: Mapped[int] = mapped_column(Integer, nullable=False)


class RolloutPlan(Base, UUIDPrimaryKeyMixin):
    """Phase 3.5 (ACT-SRS-M3 §Phase-3.5, M3-3.5-FR-001..004, FR-010) -- one
    governed canary promotion of a candidate version within an
    (agent, environment).

    The *driver* Phase 3.4's traffic allocation was built for: each stage
    advance moves the candidate's weight through
    ``TrafficAllocationService.set_weights`` -- 3.4's atomic, revisioned,
    audited mechanism -- never by writing ``deployment_traffic_weights``
    directly. This table therefore holds no weights of its own; it holds the
    *plan* whose execution produces them, and the allocation's own revision
    chain remains the single record of what traffic actually looked like when.

    ``state`` is written in exactly one place,
    ``app.runtime.deployment.canary.CanaryRolloutService``, through the pure
    transition graph in ``app.runtime.deployment.rollout`` (mechanically
    checked, mirroring Phase 3.1's own discipline for
    ``AgentDeployment.lifecycle_state``).

    ``stable_version_id`` is nullable in the schema but required in practice
    for a staged canary: 3.4's weights must total exactly 100, so a candidate
    at 5% is unrepresentable without a stable version to hold the other 95.
    ``CanaryRolloutService.create`` rejects a staged rollout that has no
    resolvable stable version rather than silently producing a 100% cutover --
    see docs/deployment/canary.md."""

    __tablename__ = "rollout_plans"
    __table_args__ = (
        Index("ix_rollout_plans_agent_environment", "agent_id", "environment_id"),
        Index("ix_rollout_plans_state", "state"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    environment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("environments.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    candidate_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False,
    )
    stable_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=True,
    )
    # CANARY / ROLLING (Phase 3.9). The two share this entire engine -- seven
    # states, per-stage health gates, optimistic concurrency, idempotency --
    # and differ in exactly one place: where the stage weights come from. A
    # canary's stages are declared by the operator; a rolling deployment's are
    # *derived from the real registered worker fleet*, which is the substrate
    # Phase 3.6 correctly refused to pretend it had. Defaulted to CANARY so
    # every pre-3.9 row and every 3.5 code path keeps its exact meaning.
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="CANARY")
    # PENDING / IN_PROGRESS / PAUSED / SUCCEEDED / ABORTED / ROLLBACK_REQUESTED / FAILED
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    current_stage_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Evidence, not state (Phase 3.9): the fleet snapshot the stage weights
    # were computed from. A rolling deployment's steps are real capacity
    # fractions -- a fleet holding 8 and 2 slots produces 80% and 100%, not an
    # invented 25/50/75/100 -- and the fleet changes constantly. Without this,
    # "why 80?" would have no answer anywhere in the system minutes later.
    # Null for a canary, which has no cohort derivation and must not imply one.
    cohort_plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    state_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optimistic-concurrency guard -- the same ``version_id_col`` mechanism
    # ``AgentDeployment`` already uses, so two actors advancing one rollout
    # cannot both win (AC-13). ``StaleDataError`` is translated to
    # ``ROLLOUT_CONFLICT`` by the service.
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __mapper_args__ = {"version_id_col": revision}


class RolloutStage(Base, UUIDPrimaryKeyMixin):
    """Phase 3.5 (M3-3.5-FR-002) -- one stage of a rollout plan and its gates.

    All three gates must be satisfied for an advance (M3-3.5-FR-012):
    ``min_duration_seconds`` elapsed since ``entered_at``, at least
    ``min_samples`` executions observed, and health at least
    ``health_requirement``. ``entered_at`` is null until the stage becomes
    current -- an unentered stage can never satisfy its duration gate, which
    is what stops a freshly-created rollout from advancing instantly."""

    __tablename__ = "rollout_stages"
    __table_args__ = (
        UniqueConstraint("rollout_plan_id", "stage_index", name="uq_rollout_stages_plan_index"),
        CheckConstraint("target_weight >= 0 AND target_weight <= 100",
                       name="ck_rollout_stages_target_weight_range"),
        Index("ix_rollout_stages_plan_index", "rollout_plan_id", "stage_index"),
    )

    rollout_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rollout_plans.id", ondelete="CASCADE"), nullable=False,
    )
    stage_index: Mapped[int] = mapped_column(Integer, nullable=False)
    target_weight: Mapped[int] = mapped_column(Integer, nullable=False)
    min_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # HEALTHY / DEGRADED / UNHEALTHY -- the minimum health the candidate must
    # reach for this stage to clear. INSUFFICIENT_DATA and UNKNOWN never
    # satisfy any requirement (see app.runtime.deployment.rollout).
    health_requirement: Mapped[str] = mapped_column(String(16), nullable=False, default="HEALTHY")
    # MANUAL / AUTO -- AUTO stages are advanced by the interim
    # evaluate-and-advance operation (Phase 3.8 replaces its trigger with a
    # real scheduler); MANUAL stages always require an explicit advance call.
    advance_mode: Mapped[str] = mapped_column(String(8), nullable=False, default="MANUAL")
    entered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeploymentHealthEvaluation(Base, UUIDPrimaryKeyMixin):
    """Phase 3.5 (ruling #3, ACT-SRS-M3 §6, M3-3.5-FR-020..023) -- one
    AI-aware release-health verdict computed from *real runtime data*.

    Deliberately a **new table**, not a widening of the pre-existing
    ``deployment_health`` (§49/§50), which is left entirely untouched
    (ruling #3). The two answer different questions and must not be
    conflated: ``deployment_health`` is a liveness heartbeat -- "did a worker
    report in, is the process up" -- written by
    ``HealthMonitoringService.heartbeat`` from an external signal. This table
    is a *release* judgement -- "is this version behaving well enough to earn
    more traffic" -- computed by aggregating ``agent_executions`` over a
    window: success/failure/timeout rates, latency, policy denials, token and
    cost. An HTTP 200 from a heartbeat says nothing about whether the model
    started refusing every third request.

    ``health_state`` includes **INSUFFICIENT_DATA** as a first-class value
    (M3-3.5-FR-022), not a null or a special-cased HEALTHY: a 5% canary with
    two successful calls has proven nothing, and the stage gate treats it as
    such.

    ``baseline_ref`` holds the stable version's metrics over the same window
    when a baseline comparison was performed (§7), including the
    ``likely_provider_wide`` finding -- see
    ``app.runtime.deployment.health``."""

    __tablename__ = "deployment_health_evaluations"
    __table_args__ = (
        Index("ix_health_evaluations_deployment_evaluated", "deployment_id", "evaluated_at"),
        Index("ix_health_evaluations_plan_evaluated", "rollout_plan_id", "evaluated_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    deployment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_deployments.id", ondelete="SET NULL"), nullable=True,
    )
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    rollout_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rollout_plans.id", ondelete="CASCADE"), nullable=True,
    )
    # HEALTHY / DEGRADED / UNHEALTHY / INSUFFICIENT_DATA / UNKNOWN
    health_state: Mapped[str] = mapped_column(String(20), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    baseline_ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    evaluated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


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
    # Phase 4.1 (M4-4.1-FR-002, migration 0045) -- the HTTP request that created
    # this execution. Distinct from `correlation_id`: a correlation spans a whole
    # caller-defined workflow and may produce many executions, while a request id
    # names the single call that produced this one. Nullable, and never invented:
    # a system-triggered execution has no HTTP request, and rows created before
    # 4.1 have none to recover. See app/observability/trace.py.
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
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
    # --- Phase 5.7a.3: streaming & token accounting (ACT-MDL-FR-040..049,
    # FR-084..089, migration 0028) --------------------------------------
    # Nullable, not zero-default: null means "unavailable" (the provider
    # omitted usage), never estimated (ACT-MDL-FR-046) -- see
    # ModelGatewayService.invoke()/PricingService in services.py.
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_accounting_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cost_amount: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)
    cost_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    pricing_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # True only for rows computed by the pre-5.7a.3 placeholder formula
    # (total_tokens * a flat rate) -- set once, historically, by migration
    # 0028; every row computed from here on is real (False).
    cost_is_estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    time_to_first_token_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    was_streamed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stream_interrupted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # --- Phase 5.6a.3: model-driven tool invocation loop (ACT-TLX-FR-040..049,
    # migration 0032) -----------------------------------------------------
    # How many model turns the loop took (1 for a plain single-turn execution
    # with no tool calls -- unchanged behavior, see ToolLoopOrchestrator).
    loop_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # COMPLETED / MAX_ITERATIONS / TOKEN_BUDGET / WALL_CLOCK / REPEATED_CALL /
    # TOOL_DENIED -- always set once the loop actually runs; null only for
    # rows created before this phase (impossible for anything executing now).
    termination_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ExecutionMessage(Base, UUIDPrimaryKeyMixin):
    """Phase 5.6a.3 SRS ACT-TLX-FR-049 — the complete, ordered conversation
    transcript for one execution's model-driven tool loop: the initial user
    input, every assistant turn (a final answer, or a request for one or
    more tools), and every tool result (success or a 5.6a.2 structured
    ``FAILED`` result) fed back to the next turn.

    ``sequence`` is the strict, gapless ordering within one execution
    (0, 1, 2, ...) -- never inferred from ``created_at`` alone, since two
    rows in the same transaction can share a timestamp. ``loop_iteration``
    is which model turn a row belongs to (0 for the initial user message,
    matching the first model call's iteration number); a ``role="tool"``
    row shares its requesting assistant row's ``loop_iteration``.
    ``tool_calls_requested`` (JSONB, only ever set on a ``role="assistant"``
    row) is the raw ``[{"id", "name", "arguments"}, ...]`` the model
    returned that turn -- ``null`` for a final-answer turn with no tool
    request. Per-iteration token/cost/duration accounting (``ACT-TLX-FR-
    047``) lives on the assistant row for that turn, reusing Phase 5.7a.3's
    ``PricingService`` per call rather than only once for the whole
    execution."""

    __tablename__ = "execution_messages"

    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_executions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user / assistant / tool
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_calls_requested: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    loop_iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_amount: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
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
    # Phase 5.7a.3 (ACT-MDL-FR-047) -- per-attempt, not only per-execution,
    # so a retried execution's earlier (failed/timed-out) attempts still
    # show their own token usage rather than only the final one's.
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_accounting_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
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


class ModelPricing(Base, UUIDPrimaryKeyMixin):
    """Phase 5.7a.3 SRS ACT-MDL-FR-084 — per-provider, per-model pricing
    with effective dating. A price change never updates a row in place: it
    inserts a new row and closes the prior one's ``effective_to`` (see
    ``PricingService.set_price`` in ``services.py``), which is what keeps
    an already-computed historical execution's cost accurate after a price
    changes (``ACT-MDL-FR-085``, AC-16/AC-17). ``effective_to IS NULL``
    means "still the current price."""

    __tablename__ = "model_pricing"
    __table_args__ = (
        UniqueConstraint("provider", "model_name", "effective_from", name="uq_model_pricing_provider_model_from"),
    )

    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    prompt_cost_per_1k: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    completion_cost_per_1k: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    pricing_version: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProviderCredential(Base, UUIDPrimaryKeyMixin):
    """Phase 5.7a.5 SRS ACT-MDL-FR-080..083 — a per-organization, per-
    provider model-provider credential, encrypted at rest.

    ``encrypted_secret`` is a Fernet ciphertext (``app/runtime/providers/
    credential_crypto.py``) — never plaintext, never the raw API key. No
    column or property on this class ever holds the decrypted value;
    decryption happens exactly once, inline, inside
    ``ProviderCredentialService.resolve_secret`` and the result is handed
    directly to the provider call, never assigned back onto an instance of
    this class (``ACT-MDL-FR-081`` — nothing here can accidentally log or
    serialize a plaintext secret because nothing here ever holds one).
    ``__repr__`` is overridden below as a second, structural line of
    defense in case a future column is ever added carelessly.

    Unique on ``(organization_id, provider)`` — one credential per
    provider per tenant, matching ``ACT-PLT-NFR-001`` row-level tenant
    isolation (every query in ``ProviderCredentialService`` filters by
    ``organization_id``, never trusts a caller-supplied id alone)."""

    __tablename__ = "provider_credentials"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider", name="uq_provider_credentials_org_provider"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    secret_hint: Mapped[str] = mapped_column(String(8), nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover -- structural safety net, not behavior under test
        return (f"<ProviderCredential id={self.id} organization_id={self.organization_id} "
               f"provider={self.provider!r} hint=***{self.secret_hint} status={self.status}>")


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
    # Phase 5.6a.1 (ACT-TLX-FR-004) -- the HTTP action's egress declaration:
    # allowed_hosts, allow_plaintext_http, local_dev_hosts, sensitive_headers,
    # sensitive_body_fields, requires_credential, credential_header,
    # credential_scheme, max_redirects, max_response_bytes. Phase 5.6a.2
    # (ACT-TLX-FR-023, FR-024, FR-026) adds `timeout_seconds` (per-tool
    # override; falls back to this row's own `timeout_seconds` column at
    # publish time) and `idempotent` (bool, default false -- undeclared
    # means never retried). Only meaningful when tool_type == "HTTP".
    # Frozen into the version's snapshot document at publish time
    # (SnapshotBuilderService) -- see docs/runtime/gateways.md's "Egress
    # control" and "Schema validation & resilience" sections for why this
    # column itself is *not* what the egress guard or executor read from at
    # execution time (they read the frozen snapshot copy, never this live,
    # mutable row).
    http_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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
    # Phase 5.6a.1 (ACT-TLX-FR-011) -- HTTP egress recording. All nullable:
    # populated only for the HTTP action; FUNCTION/echo rows leave these null,
    # unchanged from before this phase.
    target_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # "ALLOWED" / "DENIED" -- set only when the egress guard actually ran
    # (i.e. only for the HTTP action); null for FUNCTION/echo and for any
    # denial that happened before reaching the guard (TOOL_NOT_ASSIGNED etc).
    egress_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    egress_denied_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Phase 5.6a.2 (ACT-TLX-FR-018, AC-18) -- schema validation & resilience
    # recording. `error_class` is the same `ProviderErrorClass` value Phase
    # 5.7a.4 uses for model-provider failures (AC-12: shared taxonomy, not a
    # parallel enum); null unless this attempt was classified. A retried
    # idempotent call gets one row per attempt, `attempt_number` 1, 2, 3...
    # -- see ToolGatewayService._invoke_http.
    error_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    attempt_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    validation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Phase 5.6a.3 (ACT-TLX-FR-047) -- which model-loop turn this call
    # belongs to; null for a call made outside the loop (the pre-existing
    # explicit `input_payload["tool_calls"]` mechanism, unchanged).
    loop_iteration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ToolCredential(Base, UUIDPrimaryKeyMixin):
    """Phase 5.6a.1 SRS ACT-TLX-FR-012 — a per-organization, per-tool
    credential for the HTTP action, encrypted at rest.

    Deliberately a separate table from Phase 5.7a.5's
    ``provider_credentials``, not a reuse of it: a tool credential and a
    model-provider credential authenticate to different kinds of
    resources (an arbitrary third-party HTTP API vs. a registered model
    provider identifier), and overloading ``provider_credentials.provider``
    with a tool name would blur that distinction for no real benefit. The
    storage pattern — and the encryption utility itself
    (``app/runtime/providers/credential_crypto.py``) — is reused directly;
    only the table is new. Same redaction discipline as its model-provider
    counterpart: no column or property here ever holds a decrypted value;
    decryption happens exactly once, inline, inside
    ``ToolCredentialService.resolve_secret``."""

    __tablename__ = "tool_credentials"
    __table_args__ = (
        UniqueConstraint("organization_id", "tool_id", name="uq_tool_credentials_org_tool"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tools.id", ondelete="CASCADE"), nullable=False,
    )
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    secret_hint: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover -- structural safety net, not behavior under test
        return (f"<ToolCredential id={self.id} organization_id={self.organization_id} "
               f"tool_id={self.tool_id} hint=***{self.secret_hint} status={self.status}>")


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
    # The trace identity (Phase 4.1). This column predates 4.1 and was null on
    # essentially every row; the telemetry emitter now always populates it with
    # `trace_id_for(execution)`, so "show me everything in this trace" works.
    correlation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Phase 4.1 (M4-4.1-FR-020, migration 0045) -- which *derived* span this
    # event occurred in. Spans are not stored (SRS §13); the id is a
    # deterministic UUID5 recomputed by app/observability/trace.py, so this
    # reference stays valid without a span table existing.
    span_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
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


class DeploymentEvent(Base, UUIDPrimaryKeyMixin):
    """Phase 3.1 (ACT-SRS-M3 §3.1, §13, §15) -- append-only lineage of every
    deployment lifecycle transition. Complementary to, not a replacement for,
    the pre-existing ``runtime_events``/``AuthorizationAuditEvent`` streams
    (also still written on every transition, via ``_record_event`` unchanged):
    this table is the typed, deployment-specific record (``from_state``/
    ``to_state``/``idempotency_key``), while the audit stream is the
    platform-wide security record and ``runtime_events`` feeds the Operations
    Center timeline -- see docs/deployment/lifecycle.md.

    Append-only by construction: no service method in this codebase ever
    updates or deletes a row here (mirrors ``connector_lifecycle_events``'
    and ``agent_lifecycle_events``' own precedent); the migration additionally
    revokes UPDATE/DELETE at the database level."""

    __tablename__ = "deployment_events"
    __table_args__ = (
        Index("ix_deployment_events_deployment_created", "deployment_id", "created_at"),
    )

    deployment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_deployments.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    from_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_state: Mapped[str] = mapped_column(String(24), nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IdempotencyKey(Base, UUIDPrimaryKeyMixin):
    """Phase 3.1 (ACT-SRS-M3 §3.1, §10) -- the reusable, platform-wide
    idempotency contract every later Milestone 3 command reuses. Deliberately
    a *different* table from the pre-existing, narrower ``idempotency_records``
    (Phase 5.0 §33): that one dedupes execution requests specifically (scoped
    to ``agent_id``, resolving to an ``AgentExecution`` row via a hard FK) and
    is untouched by this phase, since it sits on the M1 execution path this
    phase must not modify. This table is generic across any
    ``(organization, operation)`` pair and resolves to an opaque, JSON-encoded
    ``result_ref`` rather than a typed FK, so any future command -- deployment
    or otherwise -- can adopt it without a schema change."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("organization_id", "operation", "idempotency_key", name="uq_idempotency_keys_scope"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_ref: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RollbackTriggerPolicy(Base, UUIDPrimaryKeyMixin):
    """Phase 3.7 (ACT-SRS-M3 §Phase-3.7, M3-3.7-FR-020..024) -- the governed,
    per-tenant rules deciding *when* an automatic rollback fires.

    Scope resolution is most-specific-wins: a row naming both an environment
    and an agent beats one naming only an environment, which beats the
    organization default (``environment_id`` and ``agent_id`` both null).
    Absent any enabled policy, **nothing fires** -- automation is opt-in, and
    a tenant that never configures a policy keeps exactly the manual behaviour
    Phases 3.5 and 3.6 gave them.

    ``thresholds`` is JSONB rather than a column per signal, matching how
    ``environments.policy`` already carries this platform's other governed
    threshold sets: a new health signal should not require a migration.

    ``mode`` separates *detecting* a regression from *acting* on one.
    ``NOTIFY_ONLY`` evaluates and records exactly as ``AUTO_EXECUTE`` does but
    stops short of moving traffic -- an organization may reasonably want to
    watch the automation agree with its engineers for a month before letting
    it act, and that is their call to make rather than ours.

    ``min_samples`` is the INSUFFICIENT_DATA floor (M3-3.7-FR-023). Below it
    no trigger may fire, mirroring Phase 3.5's own discipline: a thin sample
    is not evidence of failure any more than it is evidence of health, and an
    automatic rollback fired on four requests would be indistinguishable from
    noise.

    ``cooldown_seconds`` is the anti-flap guard (AC-12) -- see
    ``app.runtime.deployment.rollback``."""

    __tablename__ = "rollback_trigger_policies"
    __table_args__ = (
        CheckConstraint("mode IN ('AUTO_EXECUTE', 'NOTIFY_ONLY')",
                        name="ck_rollback_trigger_policies_mode"),
        CheckConstraint("min_samples >= 1", name="ck_rollback_trigger_policies_min_samples"),
        CheckConstraint("cooldown_seconds >= 0", name="ck_rollback_trigger_policies_cooldown"),
        Index("ix_rollback_trigger_policies_scope",
              "organization_id", "environment_id", "agent_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("environments.id", ondelete="CASCADE"), nullable=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True,
    )
    thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="AUTO_EXECUTE")
    min_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class RollbackEvent(Base, UUIDPrimaryKeyMixin):
    """Phase 3.7 (M3-3.7-FR-011, FR-012) -- append-only, one row per rollback
    that actually happened, whatever fired it.

    ``from_version_id``/``to_version_id`` are recorded rather than derived so
    the record survives any later change to version lineage: what a rollback
    *did* is a historical fact, and reading it back through a mutable pointer
    would let the past change.

    ``evidence_ref`` holds the candidate's health metrics at the moment of
    rollback (M3-3.7-FR-012). This is the point of the table as much as the
    audit is: a rolled-back candidate is precisely the thing an engineer needs
    to diagnose, and the rollback must not be the act that destroys the reason
    for it.

    ``dedup_key`` backs the partial unique index that makes one threshold
    crossing produce exactly one automatic rollback (AC-07) -- the database
    decides the race, not application timing, the same primitive Phase 3.4
    used for ``uq_traffic_allocations_current``. It is null for manual and
    forced rollbacks, which are deliberately outside the constraint: a human
    may roll the same deployment back twice, and being refused by a uniqueness
    index would be absurd. Automation is not owed that latitude.

    ``status`` is ``IN_PROGRESS`` only between the intent being recorded and
    the traffic move committing. It is the durable half of the recovery model
    (M3-3.7-FR-050): a crash mid-rollback leaves a readable ``IN_PROGRESS``
    row, and re-evaluation resumes or completes it rather than leaving a
    half-applied allocation. ``initiated_by`` is null for an automatic
    rollback -- writing a system user id there would make the audit trail
    claim a person acted."""

    __tablename__ = "rollback_events"
    __table_args__ = (
        CheckConstraint("trigger IN ('MANUAL', 'REQUESTED', 'AUTOMATIC', 'FORCED')",
                        name="ck_rollback_events_trigger"),
        CheckConstraint("status IN ('IN_PROGRESS', 'COMPLETED', 'FAILED')",
                        name="ck_rollback_events_status"),
        Index("ix_rollback_events_deployment_created", "deployment_id", "created_at"),
        Index("ix_rollback_events_agent_env_created", "agent_id", "environment_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    deployment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_deployments.id", ondelete="CASCADE"), nullable=False,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False,
    )
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("environments.id", ondelete="SET NULL"), nullable=True,
    )
    rollout_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rollout_plans.id", ondelete="SET NULL"), nullable=True,
    )
    from_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False,
    )
    to_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False,
    )
    trigger: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="COMPLETED")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_ref: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rollback_trigger_policies.id", ondelete="SET NULL"),
        nullable=True,
    )
    initiated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    dedup_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RuntimeGovernancePolicy(Base, UUIDPrimaryKeyMixin):
    """Phase 4.3 (ACT-SRS-M4 §8-4.3, M4-4.3-FR-014) -- the configurable rules
    the runtime governance engine evaluates at its six in-loop checkpoints.

    Scope resolution is most-specific-wins, deliberately the same shape
    ``RollbackTriggerPolicy`` already established: a row naming both an
    environment and an agent beats one naming only an environment, which beats
    the organization default (``environment_id`` and ``agent_id`` both null).
    A ``organization_id`` of null is the *platform* default, which no tenant
    API can write -- see ``GovernancePolicyService``.

    **Absent any policy, this table changes nothing.** The four loop-safety
    caps are built into the engine and always apply; everything here is
    additional and opt-in. A tenant that configures nothing gets exactly the
    execution behaviour Phase 5.6a.3 gave them, which is what makes shipping an
    engine on the execution path survivable.

    ``constraints`` is JSONB rather than a column per rule, matching how
    ``environments.policy`` and ``rollback_trigger_policies.thresholds``
    already carry this platform's other governed rule sets: a new constraint
    should not require a migration. The keys are validated against
    ``app.runtime.governance.constraints.KNOWN_CONSTRAINT_KEYS`` on write, so
    a typo is rejected rather than stored as a rule that silently never fires.

    ``mandatory`` is what drives fail-closed (M4-4.3-FR-020). A mandatory
    policy that cannot be evaluated STOPs the execution; a non-mandatory one
    that cannot be evaluated is recorded and skipped. That is the governance
    plane's defining posture, and the exact inverse of the telemetry plane's
    (``app.observability``, Phase 4.1) -- see docs/runtime/runtime-governance.md.
    """

    __tablename__ = "runtime_governance_policies"
    __table_args__ = (
        Index("ix_runtime_governance_policies_scope",
              "organization_id", "environment_id", "agent_id"),
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    environment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("environments.id", ondelete="CASCADE"), nullable=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    constraints: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class RuntimeGovernanceDecision(Base, UUIDPrimaryKeyMixin):
    """Phase 4.3 (M4-4.3-FR-040..042) -- append-only lineage of every material
    governance evaluation. **This table is the answer to "why did this
    execution stop".**

    Complementary to ``agent_executions.termination_reason``, not a
    replacement for it, and the division is deliberate: the execution row
    records *what terminal state the execution reached*, which is a property
    of the execution and must stay on it for every existing reader; this table
    records *which checkpoint decided, under which policy, with what
    obligation* -- one row per material decision, of which a single execution
    may produce several (a denied tool call followed by a stop, say). One row
    could not carry that, and a column that sometimes means "the loop hit its
    iteration cap" and sometimes "policy 7f3a denied gpt-4o at
    AFTER_MODEL_RESPONSE" would serve neither.

    Append-only by construction -- no service method here ever updates or
    deletes a row -- and the migration additionally revokes UPDATE/DELETE at
    the database level, matching ``deployment_events``' precedent.

    ``trace_id`` is a plain string, not a foreign key, because a trace is not a
    row: Phase 4.2 assembles traces from existing tables rather than storing
    them. It is the same value ``app.observability.trace.trace_id_for``
    derives, so a decision joins a trace timeline without either side owning
    the other.
    """

    __tablename__ = "runtime_governance_decisions"
    __table_args__ = (
        Index("ix_runtime_governance_decisions_execution", "execution_id", "evaluated_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_executions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    trace_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    checkpoint: Mapped[str] = mapped_column(String(32), nullable=False)
    decision: Mapped[str] = mapped_column(String(12), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(48), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    obligation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runtime_governance_policies.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Phase 4.4. A budget-driven decision has no governance *policy* behind it
    # -- a budget is not a row in `runtime_governance_policies` -- so lineage
    # would lose which ceiling decided without this. Nullable and independent
    # of `policy_id`: a decision has at most one of the two.
    budget_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("budgets.id", ondelete="SET NULL"), nullable=True,
    )
    iteration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Budget(Base, UUIDPrimaryKeyMixin):
    """Phase 4.4 (ACT-SRS-M4 §4.4, §11) -- a governed spending ceiling.

    **This table holds no cost.** Real per-execution cost lives, and only
    lives, on ``agent_executions.cost_amount`` with its ``pricing_version``
    provenance (Phase 5.7a.3). A budget is a *limit* and a *mode*; the money is
    counted from the authoritative rows. Creating a second cost store here
    would be the §13 duplication Milestone 4 has already refused twice, and it
    would be worse than the telemetry version of that mistake: two disagreeing
    copies of a financial figure are not merely confusing.

    ``mode`` is what makes budgets adoptable. An organization's first budget is
    almost never a hard limit -- it is someone watching a number for a month to
    see whether the platform agrees with their finance team. ``INFORMATIONAL``
    and ``WARNING`` observe and signal; only ``HARD_LIMIT`` and
    ``APPROVAL_REQUIRED`` reach the governance engine. The same reasoning gave
    Phase 3.7's rollback triggers a ``NOTIFY_ONLY`` mode and Phase 4.3's
    governance policies their ``mandatory`` flag.

    ``reservation_estimate`` is the one column beyond the SRS's sketch, and it
    earns its place: reserve-then-reconcile has to hold *something* before an
    execution runs, and a model call's cost is unknowable until it returns. How
    much to hold is a budget owner's tuning knob -- hold more and fewer
    executions run concurrently against a tight budget, hold less and the
    overshoot window widens. It is not derivable from anything else, so it is
    stored rather than guessed. ``NULL`` falls back to
    ``settings.BUDGET_DEFAULT_RESERVATION``.
    """

    __tablename__ = "budgets"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('ORGANIZATION', 'PROJECT', 'AGENT', 'ENVIRONMENT', 'MODEL')",
            name="ck_budgets_scope_type"),
        CheckConstraint(
            "mode IN ('INFORMATIONAL', 'WARNING', 'HARD_LIMIT', 'APPROVAL_REQUIRED')",
            name="ck_budgets_mode"),
        CheckConstraint("period IN ('DAILY', 'MONTHLY', 'EXECUTION')", name="ck_budgets_period"),
        CheckConstraint("limit_amount >= 0", name="ck_budgets_limit_non_negative"),
        Index("ix_budgets_scope", "organization_id", "scope_type", "scope_id", "enabled"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ORGANIZATION / PROJECT / AGENT / ENVIRONMENT / MODEL. `scope_id` is the
    # scoped entity's id, or NULL at ORGANIZATION scope. Deliberately not a
    # foreign key: it addresses four different tables, and a MODEL scope names
    # a model identifier that is a string, not a row anywhere -- which is what
    # `scope_value` carries.
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    scope_value: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="INFORMATIONAL")
    period: Mapped[str] = mapped_column(String(16), nullable=False, default="MONTHLY")
    limit_amount: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    reservation_estimate: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)
    # The fraction of `limit_amount` at which a WARNING budget starts
    # signalling and an APPROVAL_REQUIRED budget starts challenging.
    threshold_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class BudgetReservation(Base, UUIDPrimaryKeyMixin):
    """Phase 4.4 (M4-4.4-FR-020..024) -- **the financial-consistency core.**

    The failure this table exists to prevent (§11, §35): twenty workers each
    read *"$9 remaining"* against a $10 budget, each decide they may spend $9,
    and $180 is spent against a $10 budget. Reading a balance and then acting
    on it is not safe when the read and the act are separated by a model call.

    So a reservation *claims* an estimate before the execution runs -- the next
    worker to look sees that amount already gone -- and is **reconciled** to
    the real cost afterwards, releasing whatever was over-held.

    **The claim is serialized by a ``FOR UPDATE`` on the budget row**, not by an
    in-process lock, which §11 forbids explicitly and which would in any case
    be worthless across the worker fleet Phase 3.9 built. See
    ``ReservationService.reserve`` for the exact sequence and for the precise
    guarantee it does and does not give.

    **Idempotency is the database's, not a poll loop's.** A partial unique index
    on ``(budget_id, execution_id) WHERE status <> 'RELEASED'`` means one
    execution holds at most one live reservation against one budget -- Postgres
    refuses the second insert rather than the application remembering not to
    try. A *released* reservation does not participate, so a retried attempt
    can claim afresh, which is what makes an execution's second attempt behave
    like its first. Same reasoning as Phase 3.1's ``IdempotencyKey`` unique
    constraint (the constraint *is* the concurrency primitive), reached without
    its claim-then-poll machinery because a reservation has a natural key and
    no result to await.

    ``status`` is the whole lifecycle: ``RESERVED`` (held, execution in
    flight), ``RECONCILED`` (actual known, counted for real), ``RELEASED`` (the
    execution died or never spent; the hold is returned). A crashed worker's
    reservation is released by the same stale-recovery path that recovers its
    execution (M4-4.4-FR-023) -- a reservation that could leak would let one
    crash permanently shrink a tenant's budget.
    """

    __tablename__ = "budget_reservations"
    __table_args__ = (
        CheckConstraint("status IN ('RESERVED', 'RECONCILED', 'RELEASED')",
                        name="ck_budget_reservations_status"),
        CheckConstraint("reserved_amount >= 0", name="ck_budget_reservations_amount"),
        # The remaining-budget sum reads exactly these three columns.
        Index("ix_budget_reservations_period", "budget_id", "period_key", "status"),
        Index("ix_budget_reservations_execution", "execution_id"),
        Index("uq_budget_reservations_live", "budget_id", "execution_id",
              unique=True, postgresql_where=text("status <> 'RELEASED'")),
    )

    budget_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False,
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_executions.id", ondelete="CASCADE"), nullable=False,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    reserved_amount: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    actual_amount: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="RESERVED")
    # The bucket this counts against: "2026-08-28" (DAILY), "2026-08"
    # (MONTHLY), or the execution id (EXECUTION -- each execution is its own).
    period_key: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    reserved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
