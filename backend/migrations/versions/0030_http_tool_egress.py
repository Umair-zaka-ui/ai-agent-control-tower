"""Phase 5.6a.1 - HTTP Tool Execution & Egress Control.

Three purposes, additive:

1. **`tools.http_config`** (JSONB, nullable) — the per-tool HTTP action
   declaration: allowed hosts, whether plaintext HTTP is permitted (and
   for which declared local-dev hosts), sensitive header/body-field names
   to redact, whether a credential is required, and redirect/size/timeout
   caps. This is the "tool definition" `ACT-TLX-FR-004` requires the
   egress allowlist be declared in.

2. **`tool_calls` egress/HTTP columns** — none of these pre-existed
   (verified against the live schema before writing this migration, per
   the build prompt's own instruction to check first): `target_host`,
   `target_path`, `http_method`, `http_status`, `request_bytes`,
   `response_bytes`, `egress_decision`, `egress_denied_reason`.

3. **`tool_credentials`** — per-organization, per-tool encrypted
   credentials, the same shape and encryption utility
   (`credential_crypto.py`) Phase 5.7a.5 built for model-provider
   credentials, reused directly rather than duplicated — a distinct
   concern (a different resource being authenticated to) but the
   identical storage pattern.

Additive: no column is dropped or retyped.

Revision ID: 0030_http_tool_egress  (<=32 chars: alembic_version.version_num is varchar(32))
Revises: 0029_provider_credentials
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0030_http_tool_egress"
down_revision: str | None = "0029_provider_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- tools: the HTTP action declaration ------------------------------------
    op.add_column("tools", sa.Column("http_config", JSONB(), nullable=True))

    # --- tool_calls: egress/HTTP recording (ACT-TLX-FR-011) --------------------
    op.add_column("tool_calls", sa.Column("target_host", sa.String(length=255), nullable=True))
    op.add_column("tool_calls", sa.Column("target_path", sa.Text(), nullable=True))
    op.add_column("tool_calls", sa.Column("http_method", sa.String(length=10), nullable=True))
    op.add_column("tool_calls", sa.Column("http_status", sa.Integer(), nullable=True))
    op.add_column("tool_calls", sa.Column("request_bytes", sa.Integer(), nullable=True))
    op.add_column("tool_calls", sa.Column("response_bytes", sa.Integer(), nullable=True))
    op.add_column("tool_calls", sa.Column("egress_decision", sa.String(length=20), nullable=True))
    op.add_column("tool_calls", sa.Column("egress_denied_reason", sa.String(length=64), nullable=True))

    # --- tool_credentials (ACT-TLX-FR-012) --------------------------------------
    op.create_table(
        "tool_credentials",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("tool_id", sa.UUID(), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("secret_hint", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tool_id"], ["tools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("organization_id", "tool_id", name="uq_tool_credentials_org_tool"),
    )
    op.create_index("ix_tool_credentials_organization_id", "tool_credentials", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_tool_credentials_organization_id", table_name="tool_credentials")
    op.drop_table("tool_credentials")

    op.drop_column("tool_calls", "egress_denied_reason")
    op.drop_column("tool_calls", "egress_decision")
    op.drop_column("tool_calls", "response_bytes")
    op.drop_column("tool_calls", "request_bytes")
    op.drop_column("tool_calls", "http_status")
    op.drop_column("tool_calls", "http_method")
    op.drop_column("tool_calls", "target_path")
    op.drop_column("tool_calls", "target_host")

    op.drop_column("tools", "http_config")
