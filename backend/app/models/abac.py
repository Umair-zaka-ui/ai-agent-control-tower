"""ABAC engine models (Phase 4.3.5 §21).

Context-aware authorization on top of RBAC + resource authorization:
policies (versioned, lifecycle-managed), the attribute catalog, the
evaluation log, and time-boxed policy exceptions.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ABACPolicy(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """§6, §7 — one *version* of a policy. Versions of the same logical policy
    share ``policy_family_id``; at most one version per family is ACTIVE.
    ``organization_id`` NULL = platform-level (applies to every tenant and may
    not be overridden by organization policies, §40.6)."""

    __tablename__ = "abac_policies"

    policy_family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # DRAFT / VALIDATED / ACTIVE / DISABLED / DEPRECATED / ARCHIVED (§7).
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT", index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    combining_algorithm: Mapped[str] = mapped_column(
        String(30), nullable=False, default="DENY_OVERRIDES"
    )
    # PLATFORM / ORGANIZATION / BUSINESS_UNIT / DEPARTMENT / TEAM / PROJECT / RESOURCE (§12).
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, default="ORGANIZATION")
    scope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # §11 — {"resource_types": [...], "actions": [...], "identity_types": [...],
    #        "roles": [...], "classifications": [...]}; empty/missing = match all.
    target: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # §9 — nested {"all"/"any"/"not"/leaf} tree; validated + normalized at publish (§28).
    conditions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    effect: Mapped[str] = mapped_column(String(30), nullable=False, default="DENY")
    obligations: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ABACPolicyVersion(Base, UUIDPrimaryKeyMixin):
    """§7, §21 — immutable snapshot taken whenever a version is published.
    Published policy history may never be deleted (§40.13)."""

    __tablename__ = "abac_policy_versions"

    policy_family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AttributeDefinition(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """§20 — the attribute registry. Only registered, enabled attributes may be
    referenced by a policy; each declares its type and supported operators."""

    __tablename__ = "attribute_definitions"

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    # SUBJECT / RESOURCE / ACTION / ENVIRONMENT / AI (§5).
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    data_type: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PUBLIC / INTERNAL / RESTRICTED — RESTRICTED values are redacted from
    # user-facing explanations and logs (§16, §40.7).
    sensitivity: Mapped[str] = mapped_column(String(20), nullable=False, default="INTERNAL")
    supported_operators: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ABACEvaluation(Base, UUIDPrimaryKeyMixin):
    """§21, §36 — one row per evaluation: the decision, matched policies,
    obligations and the (redacted) explanation for the evaluation viewer."""

    __tablename__ = "abac_evaluations"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    identity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    matched_policy_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    obligations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    explanation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    evaluation_time_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ABACPolicyException(Base, UUIDPrimaryKeyMixin):
    """§21 — a time-boxed, approved exemption from one policy for one subject
    (optionally narrowed to one resource). Expires automatically (§40.12)."""

    __tablename__ = "abac_policy_exceptions"

    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("abac_policies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    subject_type: Mapped[str] = mapped_column(String(30), nullable=False, default="USER")
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
