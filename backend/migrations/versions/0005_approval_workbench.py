"""Phase 3 Part 3.4 - approval queue & human review workbench.

Adds two new ``approval_decision`` enum values (ESCALATED, EXPIRED) and three
columns to ``approvals``: the currently assigned reviewer, the escalation target
and the escalation timestamp.

Revision ID: 0005_approval_workbench
Revises: 0004_policy_mgmt
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0005_approval_workbench"
down_revision: str | None = "0004_policy_mgmt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New approval_decision enum values. ADD VALUE cannot run inside a
    # transaction block, so commit the implicit transaction first.
    op.execute("COMMIT")
    op.execute("ALTER TYPE approval_decision ADD VALUE IF NOT EXISTS 'ESCALATED'")
    op.execute("ALTER TYPE approval_decision ADD VALUE IF NOT EXISTS 'EXPIRED'")

    op.add_column(
        "approvals",
        sa.Column("assigned_to_user_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_approvals_assigned_to_users",
        "approvals",
        "users",
        ["assigned_to_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_approvals_assigned_to_user_id", "approvals", ["assigned_to_user_id"]
    )
    op.add_column(
        "approvals",
        sa.Column("escalation_target", sa.Text(), nullable=True),
    )
    op.add_column(
        "approvals",
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("approvals", "escalated_at")
    op.drop_column("approvals", "escalation_target")
    op.drop_index("ix_approvals_assigned_to_user_id", table_name="approvals")
    op.drop_constraint("fk_approvals_assigned_to_users", "approvals", type_="foreignkey")
    op.drop_column("approvals", "assigned_to_user_id")
    # Note: Postgres cannot easily drop enum values; ESCALATED/EXPIRED remain.
