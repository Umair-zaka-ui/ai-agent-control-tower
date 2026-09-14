"""Phase 5.6 (M5.6) - Runtime Threat Detection & Containment.

Additive, reversible, tenant-scoped. Two new tables; no existing table
changed, no data backfill.

  * ``threat_findings`` - a runtime-event finding (distinct from Phase 5.5's
    standing-state ``posture_findings`` - a threat is "this happened just
    now", posture is "this is how things stand"), with the same 4.7 finding
    lifecycle shape (``app.slo.states`` imported, not re-spelled). A
    dedicated table for the same reason 4.5/4.7/5.5 each chose one over a
    discriminator: what the row is *about* differs from every existing
    finding/alert table.

  * ``containment_actions`` - a record of one containment action: which
    authority was invoked (or truthfully refused), the threat/operator that
    triggered it, the agent's control_state at the time (the truthful-
    containment signal), the result, and whether/how it can be reversed.
    **This table records; it does not enforce.** It has no status value that
    represents an enforcement outcome the table itself produced - every
    EXECUTED row points at a real authority's own row (a kill-switch audit
    event, a revoked ``agent_tools``/``agent_capabilities`` row, a disabled
    connector instance, a governance policy) via ``authority_ref``.

Revision ID: 0059_threat_containment
Revises: 0058_security_posture
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0059_threat_containment"
down_revision = "0058_security_posture"
branch_labels = None
depends_on = None

_SEVERITY = ("INFO", "WARNING", "HIGH", "CRITICAL")
_FINDING_STATUS = ("OPEN", "ACKNOWLEDGED", "RESOLVED", "SUPPRESSED")
_OUTCOME = ("FINDING", "INSUFFICIENT_DATA")

_ACTION_TYPES = (
    "TERMINATE_EXECUTION", "SUSPEND_AGENT", "DENY_TOOL", "REVOKE_CAPABILITY",
    "ISOLATE_CREDENTIAL", "DISABLE_INTEGRATION", "REQUIRE_APPROVAL",
)
_AUTHORITIES = (
    "KILL_SWITCH", "GOVERNANCE_POLICY", "TOOL_LIFECYCLE", "CAPABILITY_LIFECYCLE",
    "CREDENTIAL_LIFECYCLE", "CONNECTOR_LIFECYCLE",
)
_TRIGGERS = ("THREAT", "OPERATOR")
_ACTION_STATUS = ("RECOMMENDED", "PENDING_CONFIRMATION", "EXECUTED", "REFUSED", "FAILED", "REVERTED")


def upgrade() -> None:
    op.create_table(
        "threat_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("rule_version", sa.String(length=16), nullable=False, server_default="1"),
        sa.Column("ruleset_version", sa.String(length=16), nullable=False, server_default="1"),
        sa.Column("outcome", sa.String(length=20), nullable=False, server_default="FINDING"),
        sa.Column("severity", sa.String(length=12), nullable=False, server_default="WARNING"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="OPEN"),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("attribution", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default="{}"),
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
        sa.CheckConstraint("severity IN " + str(_SEVERITY), name="ck_threat_findings_severity"),
        sa.CheckConstraint("status IN " + str(_FINDING_STATUS), name="ck_threat_findings_status"),
        sa.CheckConstraint("outcome IN " + str(_OUTCOME), name="ck_threat_findings_outcome"),
    )
    op.create_index("ix_threat_findings_org_status_sev", "threat_findings",
                    ["organization_id", "status", "severity"])
    op.create_index("ix_threat_findings_agent", "threat_findings", ["agent_id"])
    op.create_index("ix_threat_findings_org_rule", "threat_findings", ["organization_id", "rule_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_threat_findings_active "
        "ON threat_findings (organization_id, dedup_key) "
        "WHERE status IN ('OPEN', 'ACKNOWLEDGED')"
    )

    op.create_table(
        "containment_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("authority", sa.String(length=32), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("threat_finding_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("threat_findings.id", ondelete="SET NULL"), nullable=True),
        sa.Column("triggered_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("automated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("control_state_at_time", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="RECOMMENDED"),
        sa.Column("requires_confirmation", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("confirmed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("refusal_reason", sa.Text(), nullable=True),
        sa.Column("authority_ref", postgresql.JSONB(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("reversible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("action_type IN " + str(_ACTION_TYPES), name="ck_containment_actions_type"),
        sa.CheckConstraint("authority IN " + str(_AUTHORITIES), name="ck_containment_actions_authority"),
        sa.CheckConstraint("trigger IN " + str(_TRIGGERS), name="ck_containment_actions_trigger"),
        sa.CheckConstraint("status IN " + str(_ACTION_STATUS), name="ck_containment_actions_status"),
    )
    op.create_index("ix_containment_actions_org_status", "containment_actions",
                    ["organization_id", "status"])
    op.create_index("ix_containment_actions_agent", "containment_actions", ["agent_id"])
    op.create_index("ix_containment_actions_threat", "containment_actions", ["threat_finding_id"])


def downgrade() -> None:
    op.drop_index("ix_containment_actions_threat", table_name="containment_actions")
    op.drop_index("ix_containment_actions_agent", table_name="containment_actions")
    op.drop_index("ix_containment_actions_org_status", table_name="containment_actions")
    op.drop_table("containment_actions")

    op.drop_index("uq_threat_findings_active", table_name="threat_findings")
    op.drop_index("ix_threat_findings_org_rule", table_name="threat_findings")
    op.drop_index("ix_threat_findings_agent", table_name="threat_findings")
    op.drop_index("ix_threat_findings_org_status_sev", table_name="threat_findings")
    op.drop_table("threat_findings")
