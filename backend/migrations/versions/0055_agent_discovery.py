"""Phase 5.2 (M5.2) - Agent Discovery Framework.

Four new tables, all additive, reversible, tenant-scoped, no existing table
changed, no data backfill, no decrypt-behaviour change. None duplicates the
canonical ``agents`` registry -- reconciliation writes to it through the
Phase 5.1 ``AgentControlStateService`` / ``AgentProvenanceService`` seam.

  * ``discovery_sources``      - configured, tenant-scoped external systems.
  * ``discovery_runs``         - one sweep of a source.
  * ``discovery_observations`` - APPEND-ONLY evidence. UPDATE/DELETE are
                                  revoked from the application role, the same
                                  discipline migration ``0047`` established
                                  for ``runtime_governance_decisions`` --
                                  evidence must not be editable after the
                                  fact, only superseded by a newer row.
  * ``discovery_findings``     - the no-silent-merge/staleness escape hatch.

Revision ID: 0055_agent_discovery
Revises: 0054_agent_asset_model
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0055_agent_discovery"
down_revision = "0054_agent_asset_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovery_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("adapter_key", sa.String(length=64), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("encrypted_secret", sa.Text(), nullable=True),
        sa.Column("secret_hint", sa.String(length=20), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("missed_sweeps_before_stale", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_status", sa.String(length=16), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "name", name="uq_discovery_sources_org_name"),
    )
    op.create_index("ix_discovery_sources_organization_id", "discovery_sources", ["organization_id"])

    op.create_table(
        "discovery_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("discovery_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("trigger", sa.String(length=16), nullable=False, server_default="SCHEDULED"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkpoint", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("observations_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("agents_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("agents_linked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("findings_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED')",
                           name="ck_discovery_runs_status"),
        sa.CheckConstraint("trigger IN ('SCHEDULED', 'MANUAL')", name="ck_discovery_runs_trigger"),
    )
    op.create_index("ix_discovery_runs_organization_id", "discovery_runs", ["organization_id"])
    op.create_index("ix_discovery_runs_source_id", "discovery_runs", ["source_id"])

    op.create_table(
        "discovery_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("discovery_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("discovery_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_identifier", sa.String(length=500), nullable=False),
        sa.Column("normalized_payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=False, server_default="1.00"),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_discovery_observations_confidence"),
    )
    op.create_index("ix_discovery_observations_organization_id", "discovery_observations", ["organization_id"])
    op.create_index("ix_discovery_observations_source_id", "discovery_observations", ["source_id"])
    op.create_index("ix_discovery_observations_run_id", "discovery_observations", ["run_id"])
    # The reconciliation scan key (SRS M5.2 §7) - source + external identifier,
    # newest first, is how ReconciliationService finds "the latest evidence for
    # this external agent" and how staleness finds "was this identifier seen in
    # the current run".
    op.create_index(
        "ix_discovery_observations_source_external_observed",
        "discovery_observations", ["source_id", "external_identifier", "observed_at"],
    )
    # Append-only: no UPDATE or DELETE, ever, from the application role -- the
    # same immutability discipline migration 0047 gave
    # ``runtime_governance_decisions``. A bad/hostile observation is evidence
    # to be weighed, never a row that can be quietly edited after the fact.
    op.execute("REVOKE UPDATE, DELETE ON discovery_observations FROM PUBLIC")

    op.create_table(
        "discovery_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("finding_type", sa.String(length=30), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("discovery_sources.id", ondelete="CASCADE"), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("discovery_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("observation_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("discovery_observations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("external_identifier", sa.String(length=500), nullable=True),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="OPEN"),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("finding_type IN ('RECONCILIATION_AMBIGUOUS', 'STALE_AGENT')",
                           name="ck_discovery_findings_type"),
        sa.CheckConstraint("status IN ('OPEN', 'RESOLVED', 'DISMISSED')", name="ck_discovery_findings_status"),
    )
    op.create_index("ix_discovery_findings_organization_id", "discovery_findings", ["organization_id"])
    op.create_index("ix_discovery_findings_agent_id", "discovery_findings", ["agent_id"])
    # One OPEN staleness finding per agent - re-observation resolves it rather
    # than accumulating duplicates (the "one condition = one alert" precedent
    # migration 0050 established for ``runtime_alerts``).
    op.execute(
        "CREATE UNIQUE INDEX uq_discovery_findings_open_stale_agent "
        "ON discovery_findings (agent_id) "
        "WHERE finding_type = 'STALE_AGENT' AND status = 'OPEN'"
    )


def downgrade() -> None:
    op.drop_index("uq_discovery_findings_open_stale_agent", table_name="discovery_findings")
    op.drop_index("ix_discovery_findings_agent_id", table_name="discovery_findings")
    op.drop_index("ix_discovery_findings_organization_id", table_name="discovery_findings")
    op.drop_table("discovery_findings")

    op.drop_index("ix_discovery_observations_source_external_observed", table_name="discovery_observations")
    op.drop_index("ix_discovery_observations_run_id", table_name="discovery_observations")
    op.drop_index("ix_discovery_observations_source_id", table_name="discovery_observations")
    op.drop_index("ix_discovery_observations_organization_id", table_name="discovery_observations")
    op.drop_table("discovery_observations")

    op.drop_index("ix_discovery_runs_source_id", table_name="discovery_runs")
    op.drop_index("ix_discovery_runs_organization_id", table_name="discovery_runs")
    op.drop_table("discovery_runs")

    op.drop_index("ix_discovery_sources_organization_id", table_name="discovery_sources")
    op.drop_table("discovery_sources")
