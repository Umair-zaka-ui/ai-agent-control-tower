"""Phase 5.5 (M5.5) - Security Posture & Shadow Findings: the standing
posture-finding record and per-tenant rule settings.

**A dedicated ``posture_findings`` table, not a discriminator on
``runtime_alerts``** (ADR-0019). Phase 4.7 kept its evidence in its own
tables (``slo_evaluations`` / ``behavioral_findings``) and pointed a shared
alert lifecycle at them; Phase 4.5 chose a new table over a ``signal_type``
discriminator on ``deployment_health_evaluations`` because *what each table is
about* differs. A posture finding is standing risk state about an asset (a
rule, a control, evidence rows in 5.1-5.4, a remediation) - not a runtime
condition worth paging on. The **lifecycle shape** is reused verbatim:
``app.slo.states`` (``AlertStatus`` / ``ALLOWED_TRANSITIONS`` /
``ACTIVE_ALERT_STATUSES``) is imported, not re-spelled.

**No shadow boolean** - "shadow" is a query over ``rule_id`` (the shadow-class
rule set, ``app.posture.rules.SHADOW_RULE_IDS``). **No opaque score** - any
summary is a deterministic function of the open findings
(``app.posture.summary``). **Findings are signals** - nothing in
``app/posture`` enforces (AST-proven); the 4.3 engine + kill switch stay the
sole enforcers.
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
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin

# Aligned, character-for-character, with the 4.7 alert lifecycle.
POSTURE_SEVERITIES = ("INFO", "WARNING", "HIGH", "CRITICAL")
POSTURE_STATUSES = ("OPEN", "ACKNOWLEDGED", "RESOLVED", "SUPPRESSED")
# FINDING = a real posture finding. INSUFFICIENT_DATA = a rule that could not
# evaluate (the evidence it needs is absent) -- recorded explicitly so it is
# never a silent "no finding = healthy" (unknown != safe). Excluded from the
# summary/score.
POSTURE_OUTCOMES = ("FINDING", "INSUFFICIENT_DATA")


class PostureFinding(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "posture_findings"
    __table_args__ = (
        CheckConstraint(f"severity IN {POSTURE_SEVERITIES}", name="ck_posture_findings_severity"),
        CheckConstraint(f"status IN {POSTURE_STATUSES}", name="ck_posture_findings_status"),
        CheckConstraint(f"outcome IN {POSTURE_OUTCOMES}", name="ck_posture_findings_outcome"),
        Index("ix_posture_findings_org_status_sev", "organization_id", "status", "severity"),
        Index("ix_posture_findings_subject", "subject_type", "subject_id"),
        Index("ix_posture_findings_org_rule", "organization_id", "rule_id"),
        Index(
            "uq_posture_findings_active",
            "organization_id",
            "dedup_key",
            unique=True,
            postgresql_where=text("status IN ('OPEN', 'ACKNOWLEDGED')"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: The rule that produced this finding (``app.posture.rules``).
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: A control-framework hook for Phase 5.9 (e.g. ``OWNERSHIP.ACCOUNTABLE_OWNER``).
    control_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rule_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1")
    ruleset_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1")
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, default="FINDING")
    severity: Mapped[str] = mapped_column(String(12), nullable=False, default="WARNING")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    subject_type: Mapped[str] = mapped_column(String(24), nullable=False, default="AGENT")
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    remediation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: {"refs": [{"table": ..., "id": ..., ...}], "observed": ..., "threshold": ...}
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: {"ruleset_version": ..., "rule_version": ..., "params": {...}} -- so a
    #: score is reconstructable and a threshold change is explainable.
    governing_policy: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    dedup_key: Mapped[str] = mapped_column(String(180), nullable=False)
    recurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    suppressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suppressed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class PostureRuleSetting(Base, UUIDPrimaryKeyMixin):
    """Per-organization enable/disable + parameter overrides for a code-defined
    posture rule. ``revision`` is monotonic so a threshold change is
    deterministic and versioned (SRS §12 -- a CISO can see *why* a score
    moved). Absent row = the rule's coded defaults."""

    __tablename__ = "posture_rule_settings"
    __table_args__ = (
        UniqueConstraint("organization_id", "rule_id", name="uq_posture_rule_settings_org_rule"),
        Index("ix_posture_rule_settings_org", "organization_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


__all__ = [
    "POSTURE_SEVERITIES",
    "POSTURE_STATUSES",
    "POSTURE_OUTCOMES",
    "PostureFinding",
    "PostureRuleSetting",
]
