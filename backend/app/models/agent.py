"""Agent model - the AI agents whose actions are governed."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import AgentStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.api_key import AgentApiKey
    from app.models.organization import Organization
    from app.models.permission import Permission


class Agent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_agents_org_slug"),
        UniqueConstraint("organization_id", "external_reference", name="uq_agents_org_external_ref"),
        CheckConstraint(
            "control_state IN ('DISCOVERED', 'CLAIMED', 'REGISTERED', 'GOVERNED')",
            name="ck_agents_control_state",
        ),
        CheckConstraint(
            "origin_category IN ('NATIVE', 'EXTERNAL', 'UNKNOWN')",
            name="ck_agents_origin_category",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_type: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, name="agent_status"),
        nullable=False,
        default=AgentStatus.ACTIVE,
    )

    # --- Phase 3 Part 3.2: enterprise agent metadata ---
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False, default="1.0.0")
    capabilities: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    default_risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_allowed_risk: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    human_approval_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    auto_suspend_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="LOW")
    health: Mapped[str] = mapped_column(String(20), nullable=False, default="HEALTHY")

    # --- Phase 5.0: runtime & lifecycle management (SRS §7.1) ---
    # ``status`` above is the Phase-1 API-key/governance status; runtime
    # adds a distinct lifecycle (DRAFT..ACTIVE..RETIRED) rather than
    # repurposing it, since 20+ authorization/governance call sites already
    # depend on ``status``'s existing ACTIVE/SUSPENDED/ARCHIVED/BLOCKED meaning.
    slug: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    owner_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    criticality: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM")
    data_classification: Mapped[str] = mapped_column(String(30), nullable=False, default="INTERNAL")
    default_environment: Mapped[str] = mapped_column(String(20), nullable=False, default="DEVELOPMENT")
    # DRAFT / VALIDATING / VALIDATED / APPROVED / ACTIVE / SUSPENDED /
    # DEPRECATED / ARCHIVED / RETIRED (SRS §10)
    lifecycle_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="ACTIVE", index=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Phase 5.1: enterprise agent registry (SRS 5.1 §6.1) ---
    # ``risk_level`` (Phase 3, above) already covers SRS §15's declared risk
    # classification (LOW/MEDIUM/HIGH/CRITICAL — "MODERATE" in the SRS maps to
    # the existing "MEDIUM"); not duplicated here.
    business_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_units.id", ondelete="SET NULL"), nullable=True
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )
    identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_identities.id", ondelete="SET NULL"), nullable=True
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    autonomy_level: Mapped[str] = mapped_column(String(30), nullable=False, default="ASSISTIVE")
    technical_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    compliance_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    support_contact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    documentation_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    repository_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # "metadata" is reserved by SQLAlchemy's declarative base; the DB column
    # keeps the SRS name via `name=` (same pattern as AgentDefinition).
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    registration_source: Mapped[str] = mapped_column(String(30), nullable=False, default="MANUAL")
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Optimistic concurrency (SRS 5.1 §53): a stale UPDATE raises
    # SQLAlchemy's ``StaleDataError``, caught at the service layer and
    # translated to ``AGENT_CONCURRENT_MODIFICATION``.
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # --- Phase 5.1 (M5.1): Universal Agent Asset Model + Ownership ---
    # These four dimensions make the one canonical registry able to describe
    # the whole spectrum — native / external / discovered / claimed /
    # registered / governed / unknown — truthfully. They are *additive* and
    # orthogonal to everything above; in particular ``control_state`` is a
    # distinct question from ``lifecycle_status`` (see below) and the existing
    # 13-state lifecycle machine is completely unchanged.
    #
    # ``control_state`` — the relationship and *real enforcement authority*
    # ACT has over this agent, NOT its operational lifecycle:
    #   DISCOVERED  — ACT knows it exists; no authority.
    #   CLAIMED     — an owner has taken responsibility; still not governed.
    #   REGISTERED  — brought under ACT's registry/policy scope.
    #   GOVERNED    — ACT has real enforcement authority (every native agent;
    #                 external agents reach this only at NATIVE/GATEWAY
    #                 enforcement, which is Phase 5.7 — not M5.1).
    # Server-authoritative: never client-settable (absent from every write
    # schema). Native rows are GOVERNED and may be in *any* lifecycle_status.
    control_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="GOVERNED", server_default="GOVERNED", index=True
    )
    # ``origin_category`` — provenance category. A small, stable set so it can
    # carry a CHECK constraint; a new vendor never forces a migration because
    # the *provider* is the soft field below.
    #   NATIVE    — created/owned/executed by ACT.
    #   EXTERNAL  — exists outside ACT (real evidence required — 5.2 provides it).
    #   UNKNOWN   — seen but not yet classified (reconciliation refines it — 5.2).
    origin_category: Mapped[str] = mapped_column(
        String(20), nullable=False, default="NATIVE", server_default="NATIVE"
    )
    # ``origin_provider`` — soft platform/vendor identifier (ACT_NATIVE,
    # MICROSOFT, AWS, GOOGLE, OPENAI, ANTHROPIC, LANGGRAPH, CREWAI, CUSTOM,
    # UNKNOWN, …). Deliberately a plain string, NOT a DB enum: a new vendor is
    # a new value, never a schema change.
    origin_provider: Mapped[str] = mapped_column(
        String(50), nullable=False, default="ACT_NATIVE", server_default="ACT_NATIVE"
    )
    # Discovery metadata — COLUMNS ONLY. Phase 5.2 populates these; M5.1
    # discovers/observes/reconciles nothing. Native rows leave them null.
    first_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discovery_source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    discovery_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="agents")
    permissions: Mapped[list["Permission"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list["AgentApiKey"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )

    # Default ``version_id_generator`` (True) auto-increments ``row_version``
    # on every UPDATE and raises ``StaleDataError`` if the row changed
    # underneath the caller — no manual increment needed in service code.
    __mapper_args__ = {"version_id_col": row_version}
