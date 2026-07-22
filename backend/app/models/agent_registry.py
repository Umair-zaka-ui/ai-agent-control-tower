"""Phase 5.1 - Enterprise Agent Registry, Definitions & Lifecycle: ownership
history, structured lifecycle events, validation runs, duplicate detection,
import/export job tracking, and legacy-migration classification.

All additive alongside the pre-existing ``agents``/``agent_definitions``
tables (see ``app/models/agent.py`` and ``app/models/runtime.py``) — nothing
here forks a parallel registry.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class AgentOwnershipHistory(Base, UUIDPrimaryKeyMixin):
    """§13 — immutable ledger of ownership-role changes."""

    __tablename__ = "agent_ownership_history"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    # BUSINESS_OWNER / TECHNICAL_OWNER / COMPLIANCE_OWNER / SECURITY_OWNER / DATA_OWNER
    owner_role: Mapped[str] = mapped_column(String(30), nullable=False)
    previous_owner_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    previous_owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    new_owner_type: Mapped[str] = mapped_column(String(30), nullable=False)
    new_owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class AgentLifecycleEvent(Base, UUIDPrimaryKeyMixin):
    """§21 — structured lifecycle-transition ledger (richer than the generic
    ``RuntimeEvent`` payload blob: real columns for the Lifecycle tab's
    timeline and for audit queries that filter on ``previous_status``/
    ``new_status`` directly)."""

    __tablename__ = "agent_lifecycle_events"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    previous_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    new_status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    authorization_decision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class AgentValidationRun(Base, UUIDPrimaryKeyMixin):
    """§26 — one run of the validation-report engine."""

    __tablename__ = "agent_validation_runs"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    # RUNNING / PASSED / FAILED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RUNNING")
    validator_version: Mapped[str] = mapped_column(String(20), nullable=False)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    errors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    checks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class AgentDuplicateMatch(Base, UUIDPrimaryKeyMixin):
    """§33 — exact/similarity duplicate-detection result + reviewer decision."""

    __tablename__ = "agent_duplicate_matches"

    source_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    candidate_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    # EXACT / SIMILAR
    match_type: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    matching_fields: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # POSSIBLE_DUPLICATE / LIKELY_DUPLICATE / CONFIRMED_DUPLICATE (§32.3)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="POSSIBLE_DUPLICATE", index=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # CONFIRM_DUPLICATE / NOT_DUPLICATE / MERGE_REQUIRED / JUSTIFIED_SEPARATE_AGENT (§64)
    review_decision: Mapped[str | None] = mapped_column(String(30), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentImportJob(Base, UUIDPrimaryKeyMixin):
    """§45 — one import batch. Processed synchronously inline (this
    environment has no background worker — see docs/runtime/workers-and-queue.md
    for the same "eager" pattern the execution queue uses), so ``status`` goes
    straight from ``PENDING`` to a terminal state within the same request."""

    __tablename__ = "agent_import_jobs"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    format: Mapped[str] = mapped_column(String(10), nullable=False)
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    # PENDING / RUNNING / COMPLETED / FAILED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    total_records: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    successful_records: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_records: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_records: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class AgentImportItem(Base, UUIDPrimaryKeyMixin):
    """§45 — per-record outcome within an import job."""

    __tablename__ = "agent_import_items"

    import_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_import_jobs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    record_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    # CREATED / UPDATED / SKIPPED / FAILED
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True,
    )
    errors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class AgentExportJob(Base, UUIDPrimaryKeyMixin):
    """§45 — one export batch. ``payload`` holds the generated content inline
    (this environment has no object-storage service for ``storage_reference``
    to point at) and is what ``GET .../export/{jobId}/download`` streams
    back."""

    __tablename__ = "agent_export_jobs"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # FULL_CONFIGURATION / INVENTORY_SUMMARY / COMPLIANCE_REPORT / MIGRATION_PACKAGE
    export_type: Mapped[str] = mapped_column(String(30), nullable=False)
    format: Mapped[str] = mapped_column(String(10), nullable=False)
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentMigrationRecord(Base, UUIDPrimaryKeyMixin):
    """§73 — legacy-agent classification audit. "Legacy" here means agent
    rows created under Phase 5.0's simpler registry before this phase shipped
    (there is no external pre-registry system in this codebase — see
    docs/runtime/registry/migration.md)."""

    __tablename__ = "agent_migration_records"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    migration_batch_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    legacy_source: Mapped[str] = mapped_column(String(100), nullable=False)
    legacy_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # MIGRATION_READY / MISSING_OWNER / MISSING_ORGANIZATION / MISSING_IDENTITY /
    # MISSING_DEFINITION / DUPLICATE / INVALID / REQUIRES_MANUAL_REVIEW
    migration_status: Mapped[str] = mapped_column(String(30), nullable=False)
    mapping_warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    migrated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    migrated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
