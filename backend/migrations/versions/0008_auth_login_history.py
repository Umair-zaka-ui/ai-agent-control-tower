"""Phase 4 Part 4.2.2.1 - human authentication: login history + lockout window.

Adds the ``login_history`` table (SRS §13): one row per authentication attempt
(success or failure), used for auditing and the account-lockout window (SRS
§10). Additive only — no existing table is modified.

Revision ID: 0008_auth_login_history
Revises: 0007_identity_lifecycle
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0008_auth_login_history"
down_revision: str | None = "0007_identity_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_history",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("failure_reason", sa.String(length=64), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("country", sa.String(length=64), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_login_history_user_id", "login_history", ["user_id"])
    op.create_index("ix_login_history_email", "login_history", ["email"])
    op.create_index("ix_login_history_success", "login_history", ["success"])
    op.create_index("ix_login_history_created_at", "login_history", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_login_history_created_at", table_name="login_history")
    op.drop_index("ix_login_history_success", table_name="login_history")
    op.drop_index("ix_login_history_email", table_name="login_history")
    op.drop_index("ix_login_history_user_id", table_name="login_history")
    op.drop_table("login_history")
