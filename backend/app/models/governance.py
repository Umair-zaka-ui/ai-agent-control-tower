"""Identity Governance & Administration models (Phase 4.3.8 §17).

``SoDRule`` backs both Separation-of-Duties and toxic-permission detection:
both are "permission set A + permission set B must not co-occur on one
identity" checks, differing only in intent — a business-process conflict vs.
raw over-privilege — so ``rule_type`` distinguishes them on one engine/table
instead of duplicating the same shape twice.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class SoDRule(Base, UUIDPrimaryKeyMixin):
    """§9, §10 — a pair of permission sets that must not co-occur.

    ``rule_type`` is ``SOD`` (a business-process conflict, e.g. "approve
    payment" + "issue payment") or ``TOXIC_PERMISSION`` (raw over-privilege,
    e.g. two admin roles combined). Lifecycle: DRAFT → ACTIVE → DISABLED;
    activation requires approval (§24)."""

    __tablename__ = "sod_rules"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    rule_type: Mapped[str] = mapped_column(String(20), nullable=False, default="SOD", index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM")
    # Permission codes (e.g. ["approval.review"]) or role names — either side of
    # the conflict. An identity trips the rule when it holds >=1 code from each.
    permissions_a: Mapped[list] = mapped_column(JSONB, nullable=False)
    permissions_b: Mapped[list] = mapped_column(JSONB, nullable=False)
    scope: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT", index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GovernanceFinding(Base, UUIDPrimaryKeyMixin):
    """§17 — a detected governance issue: SoD/toxic violation, orphaned
    account, or a privileged account due for review."""

    __tablename__ = "governance_findings"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # SOD_VIOLATION / TOXIC_PERMISSION / ORPHANED_ACCOUNT / PRIVILEGED_REVIEW_DUE
    finding_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM")
    identity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    identity_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sod_rules.id", ondelete="SET NULL"), nullable=True
    )
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # OPEN / ACKNOWLEDGED / REMEDIATED / DISMISSED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN", index=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class RemediationAction(Base, UUIDPrimaryKeyMixin):
    """§14, §17 — a remediation work item raised against a finding."""

    __tablename__ = "remediation_actions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("governance_findings.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # REMOVE_ROLE / DISABLE_ACCOUNT / DISABLE_API_KEY / EXPIRE_DELEGATION /
    # NOTIFY_MANAGER / CREATE_APPROVAL_REQUEST / REQUIRE_MFA / CREATE_SECURITY_TICKET
    action_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # PENDING / APPROVED / EXECUTED / FAILED / CANCELLED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    # MANUAL / APPROVAL / AUTOMATIC
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="MANUAL")
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    executed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GovernanceRiskScore(Base, UUIDPrimaryKeyMixin):
    """§13 — the latest computed governance risk score for one identity."""

    __tablename__ = "governance_risk_scores"
    __table_args__ = (
        UniqueConstraint("organization_id", "identity_id", name="uq_governance_risk_identity"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    identity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    identity_label: Mapped[str] = mapped_column(String(255), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    band: Mapped[str] = mapped_column(String(20), nullable=False, default="LOW", index=True)
    factors: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ComplianceReport(Base, UUIDPrimaryKeyMixin):
    """§15, §16 — a generated compliance evidence snapshot for one framework."""

    __tablename__ = "compliance_reports"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # SOC2 / ISO27001 / HIPAA / GDPR / NIST / CIS / INTERNAL
    framework: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    report_type: Mapped[str] = mapped_column(String(50), nullable=False)
    scope: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="v1")
    generated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PrivilegedAccountReview(Base, UUIDPrimaryKeyMixin):
    """§11 — a periodic review record for one identity's privileged grant."""

    __tablename__ = "privileged_account_reviews"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    identity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    identity_label: Mapped[str] = mapped_column(String(255), nullable=False)
    role_name: Mapped[str] = mapped_column(String(255), nullable=False)
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # PENDING / APPROVED / REVOKED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
