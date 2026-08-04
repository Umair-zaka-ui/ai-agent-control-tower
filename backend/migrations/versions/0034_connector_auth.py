"""Phase 2.1.2 - Connector Authentication Framework.

Additive only, two new tables (``ACT-INT-FR-020..028``):

1. **``connector_credentials``** — per-instance, per-scheme encrypted
   authentication material (API key, basic, OAuth2 client config, mTLS
   cert/key — one Fernet ciphertext bundle per row). Unique on
   ``(connector_instance_id, auth_scheme)``.

2. **``connector_oauth_tokens``** — cached OAuth2 access/refresh token
   pair per instance, encrypted, refreshed in place. Unique on
   ``connector_instance_id``.

No existing table is touched.

Revision ID: 0034_connector_auth
Revises: 0033_connector_core
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0034_connector_auth"
down_revision: str | None = "0033_connector_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connector_credentials",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("connector_instance_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("auth_scheme", sa.String(length=48), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("secret_hint", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("validation_status", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["connector_instance_id"], ["connector_instances.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("connector_instance_id", "auth_scheme", name="uq_connector_credentials_instance_scheme"),
    )
    op.create_index("ix_connector_credentials_connector_instance_id", "connector_credentials", ["connector_instance_id"])
    op.create_index("ix_connector_credentials_organization_id", "connector_credentials", ["organization_id"])

    op.create_table(
        "connector_oauth_tokens",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("connector_instance_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("encrypted_access_token", sa.Text(), nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["connector_instance_id"], ["connector_instances.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("connector_instance_id", name="uq_connector_oauth_tokens_instance"),
    )
    op.create_index("ix_connector_oauth_tokens_connector_instance_id", "connector_oauth_tokens", ["connector_instance_id"])
    op.create_index("ix_connector_oauth_tokens_organization_id", "connector_oauth_tokens", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_connector_oauth_tokens_organization_id", table_name="connector_oauth_tokens")
    op.drop_index("ix_connector_oauth_tokens_connector_instance_id", table_name="connector_oauth_tokens")
    op.drop_table("connector_oauth_tokens")

    op.drop_index("ix_connector_credentials_organization_id", table_name="connector_credentials")
    op.drop_index("ix_connector_credentials_connector_instance_id", table_name="connector_credentials")
    op.drop_table("connector_credentials")
