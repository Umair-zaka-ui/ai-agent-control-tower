"""Phase 5.2 (M5.2) - Agent Discovery Framework: the vendor-neutral discovery
domain.

Four new tables, all tenant-scoped, none duplicating truth:

  * ``discovery_sources``    - a configured external system to observe.
  * ``discovery_runs``       - one sweep of a source (scheduled or manual).
  * ``discovery_observations`` - APPEND-ONLY evidence a run collected. Never
                                 mutated after insert (no UPDATE/DELETE grant
                                 to the app role, mirroring
                                 ``runtime_governance_decisions``'s own
                                 ``REVOKE UPDATE, DELETE ... FROM PUBLIC``).
                                 An observation is *evidence*, never truth --
                                 nothing here writes ``agents`` directly.
  * ``discovery_findings``   - the "no silent merge/split" escape hatch: an
                                ambiguous/conflicting reconciliation, or a
                                staleness detection, becomes a row here for a
                                human to resolve, not an automatic action.

Reconciliation (``app/discovery/reconciliation.py``) reads observations and
*derives* canonical ``agents`` state through the Phase 5.1
``AgentControlStateService`` / ``AgentProvenanceService`` seam -- this module
adds no column to ``agents`` and no second registry.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

# The discovery-run lifecycle. A run holds no DB lock across the external
# fetch (app/discovery/service.py) -- these states describe outcome, not a
# transaction boundary.
RUN_STATUSES = ("PENDING", "RUNNING", "SUCCEEDED", "PARTIAL", "FAILED")
RUN_TRIGGERS = ("SCHEDULED", "MANUAL")
RECONCILIATION_ACTIONS = ("CREATED", "LINKED")
FINDING_TYPES = ("RECONCILIATION_AMBIGUOUS", "STALE_AGENT")
FINDING_STATUSES = ("OPEN", "RESOLVED", "DISMISSED")


class DiscoverySource(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A configured, tenant-scoped, authenticated, governed external system.

    ``adapter_key`` names an entry in the code-side adapter registry
    (``app.discovery.adapters.registry``) -- never an import path, mirroring
    the scheduler's ``handler_key`` security property (SRS M5.2 - a row can
    never make the platform import or execute arbitrary code).

    Credentials mirror ``ToolCredential``'s storage shape exactly
    (encrypted via ``app.runtime.providers.credential_crypto``, never a raw
    secret column) rather than the heavier connector ``AuthScheme`` framework
    -- a discovery source needs "one bearer token/API key", not a declared
    outbound-request auth scheme.
    """

    __tablename__ = "discovery_sources"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_discovery_sources_org_name"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    adapter_key: Mapped[str] = mapped_column(String(64), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    encrypted_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_hint: Mapped[str | None] = mapped_column(String(20), nullable=True)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    # Deterministic, configurable staleness policy (SRS M5.2 §7.3): an agent
    # linked to this source that is missing from this many consecutive runs
    # becomes a STALE_AGENT finding. Default 1 - a single miss is enough to
    # raise a (reviewable, non-destructive) finding.
    missed_sweeps_before_stale: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class DiscoveryRun(Base, UUIDPrimaryKeyMixin):
    """One sweep of a source. Durable, resumable via ``checkpoint``, and the
    idempotency anchor for a manually-triggered re-run (``idempotency_key``,
    reusing the Phase 3.1 claim-then-poll contract at the route)."""

    __tablename__ = "discovery_runs"
    __table_args__ = (
        CheckConstraint(f"status IN {RUN_STATUSES}", name="ck_discovery_runs_status"),
        CheckConstraint(f"trigger IN {RUN_TRIGGERS}", name="ck_discovery_runs_trigger"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discovery_sources.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default="SCHEDULED")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checkpoint: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    observations_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    agents_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    agents_linked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    findings_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 server_default="now()")


class DiscoveryObservation(Base, UUIDPrimaryKeyMixin):
    """APPEND-ONLY evidence. Never updated, never deleted, never read by
    anything that mutates ``agents`` directly -- ``ReconciliationService`` is
    the only code that reads this table and its output is a *derivation*,
    written through the 5.1 control-state service.

    ``normalized_payload`` is scrubbed (``app.observability.scrubbing.scrub``)
    before this row is ever constructed -- no secret shape survives into
    storage, audit, or a reconciliation finding built from it."""

    __tablename__ = "discovery_observations"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_discovery_observations_confidence"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discovery_sources.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discovery_runs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    external_identifier: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False, default=Decimal("1.00"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 server_default="now()")


class DiscoveryFinding(Base, UUIDPrimaryKeyMixin):
    """The "no silent merge/split" record, and the staleness record.

    Mirrors ``AgentDuplicateMatch``'s review-decision shape (Phase 5.1) --
    the same finding-lifecycle convention this repository already
    established (3.5/4.5/4.7's own finding tables), reused rather than a new
    shape invented for discovery."""

    __tablename__ = "discovery_findings"
    __table_args__ = (
        CheckConstraint(f"finding_type IN {FINDING_TYPES}", name="ck_discovery_findings_type"),
        CheckConstraint(f"status IN {FINDING_STATUSES}", name="ck_discovery_findings_status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    finding_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discovery_sources.id", ondelete="CASCADE"), nullable=True,
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discovery_runs.id", ondelete="SET NULL"), nullable=True,
    )
    observation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discovery_observations.id", ondelete="SET NULL"), nullable=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True,
    )
    external_identifier: Mapped[str | None] = mapped_column(String(500), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 server_default="now()")


__all__ = [
    "RUN_STATUSES", "RUN_TRIGGERS", "RECONCILIATION_ACTIONS", "FINDING_TYPES", "FINDING_STATUSES",
    "DiscoverySource", "DiscoveryRun", "DiscoveryObservation", "DiscoveryFinding",
]
