"""Phase 3 Part 3.3 - policy management metadata.

Adds severity, status, created_by, trigger_count and last_triggered_at to
``policies``.

Revision ID: 0004_policy_mgmt
Revises: 0003_agent_mgmt
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004_policy_mgmt"
down_revision: str | None = "0003_agent_mgmt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "policies",
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="MEDIUM"),
    )
    op.add_column(
        "policies",
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ENABLED"),
    )
    op.add_column(
        "policies",
        sa.Column("created_by", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_policies_created_by_users",
        "policies",
        "users",
        ["created_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "policies",
        sa.Column("trigger_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "policies",
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Backfill status from the existing enabled flag.
    op.execute("UPDATE policies SET status = 'ENABLED' WHERE enabled = true")
    op.execute("UPDATE policies SET status = 'DISABLED' WHERE enabled = false")


def downgrade() -> None:
    op.drop_constraint("fk_policies_created_by_users", "policies", type_="foreignkey")
    for column in (
        "last_triggered_at",
        "trigger_count",
        "created_by",
        "status",
        "severity",
    ):
        op.drop_column("policies", column)
