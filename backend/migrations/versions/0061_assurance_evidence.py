"""Phase 5.9 (M5.9) - Assurance, Evidence & Compliance.

Additive, reversible, tenant-scoped. Two new tables; no existing table changed,
no data backfill.

  * ``assurance_evaluations`` - one control's result against real evidence:
    PASS / FAIL / INSUFFICIENT_EVIDENCE, the evidence it read (or the absence it
    found), the as-of that evidence carries, whether that made it stale, and any
    documented exception. Note ``ck_assurance_eval_stale_never_passes``: the
    database itself refuses to hold a stale PASS, because "we checked six weeks
    ago" does not substantiate a claim about today and a false-green is the one
    artifact a compliance surface must never produce.

  * ``assurance_evidence_bundles`` - a record that evidence left the system:
    scope, the catalog and mapping versions it was produced under, a digest of
    the exported document and its DSSE signature when signed. The payload is
    deliberately NOT stored - the bundle is reconstructable from the evaluations
    it names, and a second copy could drift from the rows it claims to
    summarize.

**No control-definition or framework-mapping table.** Both live in versioned
code (``app/assurance/controls.py``, ``frameworks.py``), the way Phase 5.5's
rule catalog does: a mapping from ACT evidence to a published control is logic
that must be reviewed in a diff, not data an operator can quietly edit into
claiming something ACT cannot substantiate.

**No status, verdict or score column anywhere.** A ``compliant`` boolean or a
coverage percentage is exactly what this phase exists not to produce, and the
surest way to prevent one being rendered is for there to be nothing to render.

Revision ID: 0061_assurance_evidence
Revises: 0060_external_gov_bridge
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0061_assurance_evidence"
down_revision = "0060_external_gov_bridge"
branch_labels = None
depends_on = None

_RESULTS = ("PASS", "FAIL", "INSUFFICIENT_EVIDENCE")
_SCOPES = ("AGENT", "ORGANIZATION")


def upgrade() -> None:
    op.create_table(
        "assurance_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("control_id", sa.String(length=128), nullable=False),
        sa.Column("catalog_version", sa.String(length=16), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("result", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remediation", sa.Text(), nullable=True),
        sa.Column("exception_reason", sa.Text(), nullable=True),
        sa.Column("exception_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("exception_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(f"result IN {_RESULTS}", name="ck_assurance_eval_result"),
        sa.CheckConstraint(f"scope IN {_SCOPES}", name="ck_assurance_eval_scope"),
        # The database refuses a stale pass. Enforced here, not only in the
        # evaluator, because a false-green must not be representable at all.
        sa.CheckConstraint("NOT (stale AND result = 'PASS')",
                           name="ck_assurance_eval_stale_never_passes"),
    )
    op.create_index("ix_assurance_evaluations_organization_id",
                    "assurance_evaluations", ["organization_id"])
    op.create_index("ix_assurance_evaluations_result", "assurance_evaluations", ["result"])
    op.create_index("ix_assurance_eval_org_control", "assurance_evaluations",
                    ["organization_id", "control_id"])
    op.create_index("ix_assurance_eval_org_subject", "assurance_evaluations",
                    ["organization_id", "subject_id"])

    op.create_table(
        "assurance_evidence_bundles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("framework_id", sa.String(length=64), nullable=True),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("catalog_version", sa.String(length=16), nullable=False),
        sa.Column("mapping_version", sa.String(length=16), nullable=False),
        sa.Column("content_digest", sa.String(length=128), nullable=False),
        sa.Column("signature", postgresql.JSONB(), nullable=True),
        sa.Column("signing_key_id", sa.String(length=128), nullable=True),
        sa.Column("evaluation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("exported_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_assurance_evidence_bundles_organization_id",
                    "assurance_evidence_bundles", ["organization_id"])
    op.create_index("ix_assurance_bundle_org_created", "assurance_evidence_bundles",
                    ["organization_id", "created_at"])


def downgrade() -> None:
    op.drop_table("assurance_evidence_bundles")
    op.drop_table("assurance_evaluations")
