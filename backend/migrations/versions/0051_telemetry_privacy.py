"""Phase 4.8 - telemetry privacy, retention & access governance.

Three new tables, no change to any existing one, no data backfill. Purely
additive, reversible, downgrade-tested.

## `telemetry_capture_policies`

Per tenant / environment / agent / data-classification, a resolved capture
mode: ``METADATA_ONLY`` / ``REDACTED_CONTENT`` / ``FULL_CONTENT`` / ``DISABLED``.
A ``NULL`` in ``organization_id`` is the *platform default* row; a ``NULL`` in
``environment_id`` / ``agent_id`` / ``classification`` widens the scope the row
applies to. Precedence (most specific wins) is
``classification > agent > environment > tenant > platform-default`` and is
resolved in ``app.telemetry_privacy.policy`` -- the database only stores the
rows. ``uq_telemetry_capture_policies_scope`` keeps one row per exact scope
tuple so an operator cannot define two contradictory modes for the same target.

## `telemetry_retention_policies`

Per telemetry class -- ``metrics_aggregate`` / ``trace_metadata`` /
``trace_content`` / ``alert_history`` / ``governance_decision`` /
``financial_record`` -- a retention in days. Not one global period: financial
and audit/governance evidence outlives detailed content payloads (§24).
``uq_telemetry_retention_policies_class`` is one row per (tenant, class).

## `trace_content`

The **governed telemetry copy** of an execution's content, materialised on the
first authorised content view and never before. It is distinct from the domain
rows it is derived from (``execution_messages``, ``agent_executions.input_payload
/output_payload``, ``tool_calls.input_summary/output_summary``): those are
domain truth with a domain lifetime; this is telemetry with its own redaction,
classification and retention lifetime (§24, M4-4.8-FR-032). Secret-scrubbing and
classification redaction run **before** a row is inserted here -- the telemetry
copy is never persisted raw (§14). ``ix_trace_content_class_created`` is the
expiration-scan index; ``uq_trace_content_source`` makes materialisation
idempotent.

Revision ID: 0051_telemetry_privacy
Revises: 0050_slos_and_alerts
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0051_telemetry_privacy"
down_revision = "0050_slos_and_alerts"
branch_labels = None
depends_on = None


_CAPTURE_MODES = "('METADATA_ONLY','REDACTED_CONTENT','FULL_CONTENT','DISABLED')"
_TELEMETRY_CLASSES = (
    "('metrics_aggregate','trace_metadata','trace_content','alert_history',"
    "'governance_decision','financial_record')"
)


def upgrade() -> None:
    op.create_table(
        "telemetry_capture_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=True, index=True),
        sa.Column("environment_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("environments.id", ondelete="CASCADE"), nullable=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("classification", sa.String(32), nullable=True),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(f"mode IN {_CAPTURE_MODES}", name="ck_telemetry_capture_policies_mode"),
    )
    # One policy per exact scope tuple. COALESCE so NULL scope slots compare
    # equal -- Postgres treats NULL as distinct in a plain unique index, which
    # would let two "platform default" rows coexist.
    op.create_index(
        "uq_telemetry_capture_policies_scope", "telemetry_capture_policies",
        [sa.text("COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
         sa.text("COALESCE(environment_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
         sa.text("COALESCE(agent_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
         sa.text("COALESCE(classification, '*')")],
        unique=True,
    )

    op.create_table(
        "telemetry_retention_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=True, index=True),
        sa.Column("telemetry_class", sa.String(32), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(f"telemetry_class IN {_TELEMETRY_CLASSES}",
                           name="ck_telemetry_retention_policies_class"),
        sa.CheckConstraint("retention_days > 0", name="ck_telemetry_retention_policies_days"),
    )
    op.create_index(
        "uq_telemetry_retention_policies_class", "telemetry_retention_policies",
        [sa.text("COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
         "telemetry_class"],
        unique=True,
    )

    op.create_table(
        "trace_content",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agent_executions.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("trace_id", sa.String(100), nullable=True),
        sa.Column("source_table", sa.String(32), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("role", sa.String(20), nullable=True),
        sa.Column("classification", sa.String(32), nullable=True),
        sa.Column("mode_applied", sa.String(20), nullable=False),
        sa.Column("redacted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("secret_scrubbed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("body", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(f"mode_applied IN {_CAPTURE_MODES}",
                           name="ck_trace_content_mode"),
        sa.UniqueConstraint("execution_id", "source_table", "source_id", "sequence",
                            name="uq_trace_content_source"),
    )
    # The expiration scan is "everything of class X older than N days".
    op.create_index("ix_trace_content_created", "trace_content", ["created_at"])
    op.create_index("ix_trace_content_org_execution", "trace_content",
                    ["organization_id", "execution_id"])


def downgrade() -> None:
    op.drop_index("ix_trace_content_org_execution", table_name="trace_content")
    op.drop_index("ix_trace_content_created", table_name="trace_content")
    op.drop_table("trace_content")
    op.drop_index("uq_telemetry_retention_policies_class",
                  table_name="telemetry_retention_policies")
    op.drop_table("telemetry_retention_policies")
    op.drop_index("uq_telemetry_capture_policies_scope",
                  table_name="telemetry_capture_policies")
    op.drop_table("telemetry_capture_policies")
