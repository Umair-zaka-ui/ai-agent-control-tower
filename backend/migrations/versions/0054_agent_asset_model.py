"""Phase 5.1 (M5.1) - Universal Agent Asset Model + Ownership.

Additive, reversible, tenant-neutral, downgrade-tested. Extends the one
canonical ``agents`` registry in place (never a parallel table) with four
dimensions that let it describe native / external / discovered / claimed /
registered / governed / unknown agents truthfully:

  * ``control_state``       - the real enforcement authority ACT has over the
                              agent (DISCOVERED -> CLAIMED -> REGISTERED ->
                              GOVERNED). DISTINCT from ``lifecycle_status`` --
                              the existing 13-state lifecycle machine is
                              untouched and every existing consumer reads it
                              identically.
  * ``origin_category``     - provenance category (NATIVE / EXTERNAL / UNKNOWN).
  * ``origin_provider``     - soft platform/vendor identifier (a plain string,
                              never a DB enum, so a new vendor is never a
                              schema change).
  * discovery metadata      - ``first_observed_at`` / ``last_observed_at`` /
                              ``discovery_source_ref`` / ``discovery_confidence``
                              -- COLUMNS ONLY. Phase 5.2 populates them; M5.1
                              discovers/observes/reconciles nothing.

## Backfill (SRS M5.1 §15)

Every pre-existing agent row *is* a native agent that ACT already governs --
there is no weak-signal inference here, the backfill states a known truth.
The three NOT-NULL columns are added with a server default so the ALTER is
instant and safe on a large table; an explicit, idempotent ``UPDATE`` then
re-states that truth for every pre-existing row (re-runnable with no effect).
The server defaults are retained (matching migration 0024's own
``registration_source`` precedent) but the application always sets these
fields explicitly on both creation paths.

Changes no decrypt behaviour, touches no other table, adds no route.

Revision ID: 0054_agent_asset_model
Revises: 0053_installation_bootstrap
"""

import sqlalchemy as sa
from alembic import op

revision = "0054_agent_asset_model"
down_revision = "0053_installation_bootstrap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("control_state", sa.String(length=20), nullable=False, server_default="GOVERNED"),
    )
    op.add_column(
        "agents",
        sa.Column("origin_category", sa.String(length=20), nullable=False, server_default="NATIVE"),
    )
    op.add_column(
        "agents",
        sa.Column("origin_provider", sa.String(length=50), nullable=False, server_default="ACT_NATIVE"),
    )
    op.add_column("agents", sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agents", sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agents", sa.Column("discovery_source_ref", sa.String(length=255), nullable=True))
    op.add_column("agents", sa.Column("discovery_confidence", sa.Numeric(5, 2), nullable=True))

    # SRS M5.1 §15 - idempotent backfill: every pre-existing agent is native
    # and already governed. The server defaults above already populated the
    # rows; this restates that known truth explicitly and is re-runnable with
    # no effect (it only ever touches rows that still hold the native defaults).
    op.execute(
        "UPDATE agents SET control_state = 'GOVERNED', "
        "origin_category = 'NATIVE', origin_provider = 'ACT_NATIVE' "
        "WHERE control_state = 'GOVERNED' AND origin_category = 'NATIVE'"
    )

    op.create_check_constraint(
        "ck_agents_control_state",
        "agents",
        "control_state IN ('DISCOVERED', 'CLAIMED', 'REGISTERED', 'GOVERNED')",
    )
    op.create_check_constraint(
        "ck_agents_origin_category",
        "agents",
        "origin_category IN ('NATIVE', 'EXTERNAL', 'UNKNOWN')",
    )
    op.create_index("ix_agents_control_state", "agents", ["control_state"])


def downgrade() -> None:
    op.drop_index("ix_agents_control_state", table_name="agents")
    op.drop_constraint("ck_agents_origin_category", "agents", type_="check")
    op.drop_constraint("ck_agents_control_state", "agents", type_="check")
    op.drop_column("agents", "discovery_confidence")
    op.drop_column("agents", "discovery_source_ref")
    op.drop_column("agents", "last_observed_at")
    op.drop_column("agents", "first_observed_at")
    op.drop_column("agents", "origin_provider")
    op.drop_column("agents", "origin_category")
    op.drop_column("agents", "control_state")
