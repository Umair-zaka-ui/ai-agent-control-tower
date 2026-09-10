"""Phase 5.5 (M5.5) - Security Posture & Shadow Findings.

Additive, reversible, tenant-scoped. Two new tables; no existing table
changed, no data backfill.

  * ``posture_findings`` - a standing, explainable posture finding about an
    asset, with the 4.7 finding lifecycle (OPEN/ACKNOWLEDGED/RESOLVED/
    SUPPRESSED, DB-enforced dedup, reopen-on-recurrence). **A dedicated table
    rather than a ``source='POSTURE'`` discriminator on ``runtime_alerts``**,
    for the same reason Phase 4.5 gave for ``behavioral_findings``: a runtime
    alert is *a significant runtime condition worth an operator's queue*
    (metric/threshold/trace context, ``source IN ('SLO','BEHAVIORAL')``); a
    posture finding is *standing risk state about an asset* (a rule id, a
    control id, evidence rows in 5.1-5.4, remediation). Sharing would mean
    nullable columns on both halves and a discriminator standing in for two
    tables. The *lifecycle shape* is reused verbatim (``app.slo.states`` --
    ``AlertStatus`` / ``ALLOWED_TRANSITIONS`` / ``ACTIVE_ALERT_STATUSES``).

  * ``posture_rule_settings`` - per-organization enable/disable + parameter
    overrides for a code-defined rule, carrying a monotonic ``revision`` so a
    threshold change is deterministic and versioned (the score-
    reconstructability requirement, SRS §12). Absent row = the rule's coded
    defaults.

**No shadow boolean** (an agent is "shadow" iff it has an open shadow-class
finding -- a query over ``posture_findings.rule_id``, ``app.posture.shadow``).
**No opaque score** (any summary is a deterministic, versioned function of the
open findings -- ``app.posture.summary``). **No enforcement** (findings are
signals; ``app/posture`` has no enforcement path, AST-proven).

Revision ID: 0058_security_posture
Revises: 0057_dependency_graph
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0058_security_posture"
down_revision = "0057_dependency_graph"
branch_labels = None
depends_on = None

_SEVERITY = ("INFO", "WARNING", "HIGH", "CRITICAL")
_STATUS = ("OPEN", "ACKNOWLEDGED", "RESOLVED", "SUPPRESSED")
_OUTCOME = ("FINDING", "INSUFFICIENT_DATA")


def upgrade() -> None:
    op.create_table(
        "posture_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("control_id", sa.String(length=64), nullable=True),
        sa.Column("rule_version", sa.String(length=16), nullable=False, server_default="1"),
        sa.Column("ruleset_version", sa.String(length=16), nullable=False, server_default="1"),
        sa.Column("outcome", sa.String(length=20), nullable=False, server_default="FINDING"),
        sa.Column("severity", sa.String(length=12), nullable=False, server_default="WARNING"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="OPEN"),
        sa.Column("subject_type", sa.String(length=24), nullable=False, server_default="AGENT"),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("remediation", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("governing_policy", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("dedup_key", sa.String(length=180), nullable=False),
        sa.Column("recurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suppressed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("severity IN " + str(_SEVERITY), name="ck_posture_findings_severity"),
        sa.CheckConstraint("status IN " + str(_STATUS), name="ck_posture_findings_status"),
        sa.CheckConstraint("outcome IN " + str(_OUTCOME), name="ck_posture_findings_outcome"),
    )
    op.create_index("ix_posture_findings_org_status_sev", "posture_findings",
                    ["organization_id", "status", "severity"])
    op.create_index("ix_posture_findings_subject", "posture_findings",
                    ["subject_type", "subject_id"])
    op.create_index("ix_posture_findings_org_rule", "posture_findings",
                    ["organization_id", "rule_id"])
    # One open finding per condition (the 4.7 primitive) -- a re-evaluation
    # never multiplies findings; a RESOLVED finding re-opens on recurrence, a
    # SUPPRESSED one does not.
    op.execute(
        "CREATE UNIQUE INDEX uq_posture_findings_active "
        "ON posture_findings (organization_id, dedup_key) "
        "WHERE status IN ('OPEN', 'ACKNOWLEDGED')"
    )

    op.create_table(
        "posture_rule_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "rule_id", name="uq_posture_rule_settings_org_rule"),
    )
    op.create_index("ix_posture_rule_settings_org", "posture_rule_settings", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_posture_rule_settings_org", table_name="posture_rule_settings")
    op.drop_table("posture_rule_settings")
    op.drop_index("uq_posture_findings_active", table_name="posture_findings")
    op.drop_index("ix_posture_findings_org_rule", table_name="posture_findings")
    op.drop_index("ix_posture_findings_subject", table_name="posture_findings")
    op.drop_index("ix_posture_findings_org_status_sev", table_name="posture_findings")
    op.drop_table("posture_findings")
