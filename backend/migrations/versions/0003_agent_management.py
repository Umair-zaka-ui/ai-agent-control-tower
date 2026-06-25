"""Phase 3 Part 3.2 - enterprise agent management fields + statuses.

Adds operational metadata columns to ``agents`` and two new agent statuses
(ARCHIVED, BLOCKED).

Revision ID: 0003_agent_mgmt
Revises: 0002_phase2
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_agent_mgmt"
down_revision: str | None = "0002_phase2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New agent_status enum values. ADD VALUE cannot run inside a transaction
    # block, so commit the implicit transaction first.
    op.execute("COMMIT")
    op.execute("ALTER TYPE agent_status ADD VALUE IF NOT EXISTS 'ARCHIVED'")
    op.execute("ALTER TYPE agent_status ADD VALUE IF NOT EXISTS 'BLOCKED'")

    op.add_column("agents", sa.Column("owner", sa.String(length=255), nullable=True))
    op.add_column("agents", sa.Column("department", sa.String(length=255), nullable=True))
    op.add_column(
        "agents",
        sa.Column("version", sa.String(length=50), nullable=False, server_default="1.0.0"),
    )
    op.add_column(
        "agents",
        sa.Column(
            "capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "agents",
        sa.Column("default_risk_score", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "agents",
        sa.Column("max_allowed_risk", sa.Integer(), nullable=False, server_default="100"),
    )
    op.add_column(
        "agents",
        sa.Column(
            "human_approval_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "agents", sa.Column("auto_suspend_threshold", sa.Integer(), nullable=True)
    )
    op.add_column(
        "agents",
        sa.Column("risk_level", sa.String(length=20), nullable=False, server_default="LOW"),
    )
    op.add_column(
        "agents",
        sa.Column("health", sa.String(length=20), nullable=False, server_default="HEALTHY"),
    )


def downgrade() -> None:
    for column in (
        "health",
        "risk_level",
        "auto_suspend_threshold",
        "human_approval_required",
        "max_allowed_risk",
        "default_risk_score",
        "capabilities",
        "version",
        "department",
        "owner",
    ):
        op.drop_column("agents", column)
    # Note: Postgres cannot drop individual enum values; ARCHIVED/BLOCKED remain
    # on the agent_status type after a downgrade (harmless).
