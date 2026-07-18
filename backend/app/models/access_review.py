"""Access review campaigns (Phase 4.3.7 §14).

Periodic certification of access: a campaign snapshots the role assignments in
scope as review items; reviewers certify or revoke each one; a REVOKE removes
the underlying assignment through the RBAC service (never raw SQL), and the
campaign completes only when every item is decided.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AccessReviewCampaign(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """§14 — lifecycle DRAFT → SCHEDULED → ACTIVE → COMPLETED → ARCHIVED."""

    __tablename__ = "access_review_campaigns"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT", index=True)
    # §5 — QUARTERLY / ANNUAL / PRIVILEGED / PROJECT / EMERGENCY.
    campaign_type: Mapped[str] = mapped_column(String(30), nullable=False, default="QUARTERLY")
    # {"role_ids": [...], "department_id": ..., "include_system_roles": bool} —
    # what the campaign covers; snapshotted into items on activation.
    scope: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AccessReviewItem(Base, UUIDPrimaryKeyMixin):
    """§14 — one assignment under review. ``assignment_id`` links the live
    ``user_roles`` row so a REVOKE decision removes exactly that grant; the
    label columns keep the item legible after the assignment is gone."""

    __tablename__ = "access_review_items"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("access_review_campaigns.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    subject_label: Mapped[str] = mapped_column(String(255), nullable=False)
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    role_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    role_name: Mapped[str] = mapped_column(String(255), nullable=False)
    scope_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # PENDING / CERTIFIED / REVOKED
    decision: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
