"""Phase 4.3.2 - Enterprise Permission Engine.

Adds the engine's persistence:

- ``role_permissions.effect``   ALLOW (default) / DENY, so a role can *explicitly
                                deny* a permission — deny always wins (§16).
- ``permission_cache``          resolved permission grants per identity, versioned
                                for immediate invalidation (§10, §18).
- ``permission_versions``       per-org monotonic version; bumping it invalidates
                                every cache row for that org (§10).
- ``authorization_decisions``   one row per evaluated decision with timing (§18, §27).

Additive: no column is dropped or retyped.

Revision ID: 0017_permission_engine
Revises: 0016_rbac_foundation
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_permission_engine"
down_revision: str | None = "0016_rbac_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- role_permissions.effect ------------------------------------- #
    op.add_column(
        "role_permissions",
        sa.Column("effect", sa.String(length=10), nullable=False, server_default="ALLOW"),
    )

    # ---- permission_versions ----------------------------------------- #
    op.create_table(
        "permission_versions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", name="uq_permission_version_org"),
    )

    # ---- permission_cache -------------------------------------------- #
    op.create_table(
        "permission_cache",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("identity_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("grants_json", postgresql.JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("identity_id", name="uq_permission_cache_identity"),
    )
    op.create_index("ix_permission_cache_org", "permission_cache", ["organization_id"])

    # ---- authorization_decisions ------------------------------------- #
    op.create_table(
        "authorization_decisions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("identity_id", sa.UUID(), nullable=True),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("permission", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=50), nullable=True),
        sa.Column("resource_id", sa.UUID(), nullable=True),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("scope", sa.String(length=20), nullable=True),
        sa.Column("source_role", sa.String(length=100), nullable=True),
        sa.Column("evaluation_time_ms", sa.Float(), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_authz_decisions_identity", "authorization_decisions", ["identity_id"])
    op.create_index("ix_authz_decisions_org", "authorization_decisions", ["organization_id"])
    op.create_index("ix_authz_decisions_allowed", "authorization_decisions", ["allowed"])
    op.create_index("ix_authz_decisions_created_at", "authorization_decisions", ["created_at"])


def downgrade() -> None:
    op.drop_table("authorization_decisions")
    op.drop_index("ix_permission_cache_org", table_name="permission_cache")
    op.drop_table("permission_cache")
    op.drop_table("permission_versions")
    op.drop_column("role_permissions", "effect")
