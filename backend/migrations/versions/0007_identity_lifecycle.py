"""Phase 4 Part 4.1a - unify the identity lifecycle across all identity types.

Adds a canonical ``status`` (IdentityStatus) column to ``users`` and
``organizations`` so every identity — human, AI agent, service account,
organization and external client — shares the same lifecycle. Existing rows
default to ACTIVE.

Revision ID: 0007_identity_lifecycle
Revises: 0006_identity_foundation
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0007_identity_lifecycle"
down_revision: str | None = "0006_identity_foundation"
branch_labels = None
depends_on = None

_ACTIVE = sa.text("'ACTIVE'")


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("status", sa.String(length=30), nullable=False, server_default=_ACTIVE),
    )
    op.add_column(
        "organizations",
        sa.Column("status", sa.String(length=30), nullable=False, server_default=_ACTIVE),
    )


def downgrade() -> None:
    op.drop_column("organizations", "status")
    op.drop_column("users", "status")
