"""Phase 4.7 - SLOs, alert rules & incident signals.

Three new tables, no change to any existing one, no data backfill.

## `slo_definitions`

A runtime service objective: an SLI, a target, an observation window, an error
budget. The objective *direction* is a fixed property of the SLI
(``app.slo.sli.SLI_SPECS``), not a column - so a self-contradictory "success
rate below 0.99 is good" cannot be stored. ``uq_slo_definitions_org_name`` is
the human-facing dedup (one SLO name per tenant); the scope is deliberately not
unique, because a warn threshold and a page threshold over the same SLI/scope
are two legitimate SLOs.

## `slo_evaluations` (append-only)

One deterministic evaluation of one SLO over one window.
``uq_slo_evaluations_window`` on ``(slo_id, window_start, window_end)`` is the
idempotency primitive - the 3.8 scheduler re-running an overlapping window
produces one row, enforced by the database, the same reasoning
``uq_behavioral_findings_window`` (4.5) used.

## `runtime_alerts`

The lifecycle layer over two evidence sources (``slo_evaluations`` /
``behavioral_findings``) - one model, not two parallel concepts (§18).
``uq_runtime_alerts_active_dedup`` is a **partial** unique index over
``(organization_id, dedup_key) WHERE status IN ('OPEN','ACKNOWLEDGED')`` - one
ongoing condition is one active alert, the database deciding the race, the same
primitive ``uq_rollback_events_dedup`` (3.7) used. A RESOLVED alert re-opens on
recurrence; a SUPPRESSED one does not.

## No index added to `agent_executions` / `tool_calls`

SLI aggregation reuses the exact tenant-leading, window-bounded shape 3.5's
health engine and 4.5's behavioral engine already run over these tables -
``ix_agent_executions_org_created`` plus, for scoped SLOs,
``ix_agent_executions_agent`` / ``ix_agent_executions_version_created``, all
pre-existing. Measurement (recorded in ``docs/operations/slos.md``) showed the
per-SLO window aggregate well inside budget with no sequential scan, so this
phase adds none - the same restraint 4.2/4.4/4.5 exercised.

Purely additive, reversible, downgrade-tested.

Revision ID: 0050_slos_and_alerts
Revises: 0049_behavioral_signals
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0050_slos_and_alerts"
down_revision = "0049_behavioral_signals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "slo_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("scope_type", sa.String(16), nullable=False, server_default="ORGANIZATION"),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sli", sa.String(48), nullable=False),
        sa.Column("target", sa.Numeric(18, 6), nullable=False),
        sa.Column("window", sa.String(16), nullable=False, server_default="24h"),
        sa.Column("error_budget", sa.Numeric(18, 6), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "sli IN ('success_rate','latency_p95','timeout_rate',"
            "'provider_error_rate','tool_failure_rate','queue_delay')",
            name="ck_slo_definitions_sli"),
        sa.CheckConstraint(
            "scope_type IN ('ORGANIZATION','AGENT','VERSION','ENVIRONMENT')",
            name="ck_slo_definitions_scope_type"),
        sa.UniqueConstraint("organization_id", "name", name="uq_slo_definitions_org_name"),
    )
    op.create_index("ix_slo_definitions_org_enabled", "slo_definitions",
                    ["organization_id", "enabled"])

    op.create_table(
        "slo_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slo_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("slo_definitions.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("observed_value", sa.Numeric(18, 6), nullable=True),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("budget_consumed", sa.Numeric(18, 6), nullable=True),
        sa.Column("budget_remaining", sa.Numeric(18, 6), nullable=True),
        sa.Column("explanation", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "state IN ('MET','BREACHED','INSUFFICIENT_DATA','UNKNOWN')",
            name="ck_slo_evaluations_state"),
        sa.UniqueConstraint("slo_id", "window_start", "window_end",
                            name="uq_slo_evaluations_window"),
    )
    op.create_index("ix_slo_evaluations_slo_evaluated", "slo_evaluations",
                    ["slo_id", "evaluated_at"])
    op.create_index("ix_slo_evaluations_org_evaluated", "slo_evaluations",
                    ["organization_id", "evaluated_at"])

    op.create_table(
        "runtime_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("slo_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("slo_definitions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("severity", sa.String(12), nullable=False, server_default="WARNING"),
        sa.Column("status", sa.String(16), nullable=False, server_default="OPEN"),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agent_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("environment_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("environments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("trace_id", sa.String(100), nullable=True),
        sa.Column("metric", sa.String(48), nullable=False),
        sa.Column("threshold_value", sa.Numeric(18, 6), nullable=True),
        sa.Column("observed_value", sa.Numeric(18, 6), nullable=True),
        sa.Column("baseline_value", sa.Numeric(18, 6), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("dedup_key", sa.String(128), nullable=False),
        sa.Column("context", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("recurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint("source IN ('SLO','BEHAVIORAL')", name="ck_runtime_alerts_source"),
        sa.CheckConstraint("severity IN ('INFO','WARNING','HIGH','CRITICAL')",
                           name="ck_runtime_alerts_severity"),
        sa.CheckConstraint("status IN ('OPEN','ACKNOWLEDGED','RESOLVED','SUPPRESSED')",
                           name="ck_runtime_alerts_status"),
    )
    # One ongoing condition is one active alert -- the database decides the race
    # (M4-4.7-FR-013, AC-07), the same partial-unique primitive 3.7 used.
    op.create_index("uq_runtime_alerts_active_dedup", "runtime_alerts",
                    ["organization_id", "dedup_key"], unique=True,
                    postgresql_where=sa.text("status IN ('OPEN', 'ACKNOWLEDGED')"))
    op.create_index("ix_runtime_alerts_org_status_opened", "runtime_alerts",
                    ["organization_id", "status", "opened_at"])
    op.create_index("ix_runtime_alerts_org_severity", "runtime_alerts",
                    ["organization_id", "severity"])
    op.create_index("ix_runtime_alerts_agent", "runtime_alerts", ["agent_id", "opened_at"])


def downgrade() -> None:
    op.drop_index("ix_runtime_alerts_agent", table_name="runtime_alerts")
    op.drop_index("ix_runtime_alerts_org_severity", table_name="runtime_alerts")
    op.drop_index("ix_runtime_alerts_org_status_opened", table_name="runtime_alerts")
    op.drop_index("uq_runtime_alerts_active_dedup", table_name="runtime_alerts")
    op.drop_table("runtime_alerts")
    op.drop_index("ix_slo_evaluations_org_evaluated", table_name="slo_evaluations")
    op.drop_index("ix_slo_evaluations_slo_evaluated", table_name="slo_evaluations")
    op.drop_table("slo_evaluations")
    op.drop_index("ix_slo_definitions_org_enabled", table_name="slo_definitions")
    op.drop_table("slo_definitions")
