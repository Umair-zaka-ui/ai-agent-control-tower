"""Phase 5.9 (M5.9) - Assurance, Evidence & Compliance.

Two additive tables. Neither is a new evidence source: control definitions and
framework mappings live in **versioned code** (``app/assurance/controls.py``,
``frameworks.py``) the way Phase 5.5's rule catalog does, because a mapping is
logic that must be reviewed in a diff, not data an operator can quietly edit
into saying something ACT cannot substantiate.

  * ``assurance_evaluations`` - one control's result for one scope at one
    moment: PASS / FAIL / **INSUFFICIENT_EVIDENCE**, the evidence it read (or
    the absence it found), the as-of that evidence carries, whether that made it
    stale, and any documented exception. *Why new:* no existing table records
    "this control was evaluated against this evidence and this is what it
    showed". ``posture_findings`` records a condition, not a control evaluation
    against a framework mapping, and a finding cannot represent PASS.

  * ``assurance_evidence_bundles`` - a record of one export: scope, the
    catalog/mapping versions it was produced under, a digest of the exported
    document, and its DSSE signature when signed. *Why new:* nothing records
    that evidence left the system, and for an auditor the export event is
    itself evidence. The bundle row stores the **digest and signature**, not the
    payload - the payload is reconstructable from the evaluations it names, and
    storing a second copy would create a record that could drift from the rows
    it claims to summarize.

**There is no status, verdict or score column anywhere in this module.** A
``compliant`` boolean or a coverage percentage is exactly the artifact this
phase exists not to produce, and the surest way to prevent one being rendered
is for there to be nothing to render. ``test_ac04`` asserts that structurally
over these tables' columns.
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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin

#: The only three results a control can produce. There is deliberately no
#: fourth value meaning "compliant" and no aggregate verdict.
ASSURANCE_RESULTS = ("PASS", "FAIL", "INSUFFICIENT_EVIDENCE")

ASSURANCE_SCOPES = ("AGENT", "ORGANIZATION")


class AssuranceEvaluation(Base, UUIDPrimaryKeyMixin):
    """One control's result against real evidence at a point in time."""

    __tablename__ = "assurance_evaluations"
    __table_args__ = (
        CheckConstraint(f"result IN {ASSURANCE_RESULTS}", name="ck_assurance_eval_result"),
        CheckConstraint(f"scope IN {ASSURANCE_SCOPES}", name="ck_assurance_eval_scope"),
        # A stale result can never be a PASS. The rule is enforced by the
        # database, not only by the evaluator that writes these rows, because
        # "stale but passing" is precisely the false-green this phase exists to
        # prevent and it must not be representable.
        CheckConstraint("NOT (stale AND result = 'PASS')",
                        name="ck_assurance_eval_stale_never_passes"),
        Index("ix_assurance_eval_org_control", "organization_id", "control_id"),
        Index("ix_assurance_eval_org_subject", "organization_id", "subject_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    control_id: Mapped[str] = mapped_column(String(128), nullable=False)
    #: The catalog version that produced this result, so an old evaluation can
    #: be traced to the definition it was produced under rather than reread
    #: under today's.
    catalog_version: Mapped[str] = mapped_column(String(16), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The agent this is about; NULL for an organization-scoped control.
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True,
    )
    result: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    #: What the control read — or the absence it found. A result that cannot
    #: name its evidence is not reconstructable, and an auditor has no reason
    #: to believe it.
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: When the evidence was produced. NULL means there was none.
    evidence_as_of: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    remediation: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: A documented, audited exception. Never silences a result — the result
    #: still reads FAIL or INSUFFICIENT_EVIDENCE; this records that someone
    #: accepted it, who, and why.
    exception_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    exception_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    exception_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())


class AssuranceEvidenceBundle(Base, UUIDPrimaryKeyMixin):
    """A record that evidence left the system.

    Stores the digest and signature, never the payload: the bundle is
    reconstructable from the evaluations it names, and keeping a second copy
    would create a record that could drift from the rows it claims to
    summarize.
    """

    __tablename__ = "assurance_evidence_bundles"
    __table_args__ = (
        Index("ix_assurance_bundle_org_created", "organization_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    framework_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    catalog_version: Mapped[str] = mapped_column(String(16), nullable=False)
    mapping_version: Mapped[str] = mapped_column(String(16), nullable=False)
    #: SHA-256 over the canonicalized bundle document — what the signature
    #: covers, and what a recipient recomputes to detect tampering.
    content_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    #: The DSSE envelope from M4.11's signing provider, when signing succeeded.
    #: NULL means the bundle was exported unsigned, which the export result says
    #: out loud rather than letting a caller assume tamper-evidence it lacks.
    signature: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    signing_key_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    evaluation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exported_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())


__all__ = [
    "ASSURANCE_RESULTS",
    "ASSURANCE_SCOPES",
    "AssuranceEvaluation",
    "AssuranceEvidenceBundle",
]
