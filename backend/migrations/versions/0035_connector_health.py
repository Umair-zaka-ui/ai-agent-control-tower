"""Phase 2.1.3 - Connector Registry & Health.

Additive only (``ACT-INT-FR-040..047``):

1. **``connector_health_checks``** (new table) — append-only history of
   every health check (on-demand or the interim scheduler's sweep):
   reachability, auth validity, overall result, a safe reason, latency.

2. **``connector_instances``** gains two nullable columns:
   ``last_health_check_at`` (TIMESTAMP) and ``current_health``
   (VARCHAR(16)) — a fast-read cache of the latest check, derived from
   the history table, never a second source of truth.

No existing table is retyped or dropped.

Revision ID: 0035_connector_health
Revises: 0034_connector_auth
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0035_connector_health"
down_revision: str | None = "0034_connector_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("connector_instances", sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("connector_instances", sa.Column("current_health", sa.String(length=16), nullable=True))

    op.create_table(
        "connector_health_checks",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("connector_instance_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("check_type", sa.String(length=16), nullable=False),
        sa.Column("reachable", sa.Boolean(), nullable=False),
        sa.Column("auth_valid", sa.Boolean(), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["connector_instance_id"], ["connector_instances.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_connector_health_checks_connector_instance_id", "connector_health_checks", ["connector_instance_id"])
    op.create_index("ix_connector_health_checks_organization_id", "connector_health_checks", ["organization_id"])
    op.create_index("ix_connector_health_checks_checked_at", "connector_health_checks", ["checked_at"])
    op.create_index(
        "ix_connector_health_checks_instance_checked_at", "connector_health_checks",
        ["connector_instance_id", "checked_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_connector_health_checks_instance_checked_at", table_name="connector_health_checks")
    op.drop_index("ix_connector_health_checks_checked_at", table_name="connector_health_checks")
    op.drop_index("ix_connector_health_checks_organization_id", table_name="connector_health_checks")
    op.drop_index("ix_connector_health_checks_connector_instance_id", table_name="connector_health_checks")
    op.drop_table("connector_health_checks")

    op.drop_column("connector_instances", "current_health")
    op.drop_column("connector_instances", "last_health_check_at")
