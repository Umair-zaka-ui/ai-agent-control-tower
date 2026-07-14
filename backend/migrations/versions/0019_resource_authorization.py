"""Phase 4.3.4 - Enterprise resource-based authorization (RBAC + Resource ACL).

New tables (§15):

- ``resources``            the protected-resource registry: owner (+type),
                           visibility, status, optional resource policy (§6, §9, §14).
- ``resource_acl``         per-resource ACL entries: principal, permission,
                           ALLOW/DENY effect, expiry (§10).
- ``resource_shares``      explicit shares (user/team/department/organization)
                           at an access level, with expiry (§12).
- ``ownership_history``    every ownership transfer, preserved (§8).
- ``resource_delegations`` per-resource delegated access with expiry (§13).

Additive: no column dropped or retyped.

Revision ID: 0019_resource_authorization
Revises: 0018_org_hierarchy
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0019_resource_authorization"
down_revision: str | None = "0018_org_hierarchy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- resources (registry) ------------------------------------------ #
    op.create_table(
        "resources",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("resource_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("owner_type", sa.String(length=20), nullable=False, server_default="USER"),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("visibility", sa.String(length=20), nullable=False, server_default="PRIVATE"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("policy", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("resource_type", "resource_id", name="uq_resources_type_id"),
    )
    op.create_index("ix_resources_org", "resources", ["organization_id"])
    op.create_index("ix_resources_owner", "resources", ["owner_id"])
    op.create_index("ix_resources_lookup", "resources", ["resource_type", "resource_id"])

    # ---- resource_acl --------------------------------------------------- #
    op.create_table(
        "resource_acl",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("resource_id", sa.UUID(), nullable=False),
        sa.Column("principal_type", sa.String(length=20), nullable=False),
        sa.Column("principal_id", sa.UUID(), nullable=False),
        sa.Column("permission", sa.String(length=100), nullable=False),
        sa.Column("effect", sa.String(length=5), nullable=False, server_default="ALLOW"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_resource_acl_resource", "resource_acl", ["resource_id"])
    op.create_index("ix_resource_acl_principal", "resource_acl", ["principal_id"])

    # ---- resource_shares ------------------------------------------------ #
    op.create_table(
        "resource_shares",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("resource_id", sa.UUID(), nullable=False),
        sa.Column("shared_with_type", sa.String(length=20), nullable=False),
        sa.Column("shared_with_id", sa.UUID(), nullable=False),
        sa.Column("access_level", sa.String(length=10), nullable=False, server_default="READ"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_resource_shares_resource", "resource_shares", ["resource_id"])
    op.create_index("ix_resource_shares_with", "resource_shares", ["shared_with_id"])

    # ---- ownership_history ---------------------------------------------- #
    op.create_table(
        "ownership_history",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("resource_id", sa.UUID(), nullable=False),
        sa.Column("previous_owner", sa.UUID(), nullable=True),
        sa.Column("previous_owner_type", sa.String(length=20), nullable=True),
        sa.Column("new_owner", sa.UUID(), nullable=False),
        sa.Column("new_owner_type", sa.String(length=20), nullable=False, server_default="USER"),
        sa.Column("changed_by", sa.UUID(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_ownership_history_resource", "ownership_history", ["resource_id"])

    # ---- resource_delegations ------------------------------------------- #
    op.create_table(
        "resource_delegations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("resource_id", sa.UUID(), nullable=False),
        sa.Column("delegate_id", sa.UUID(), nullable=False),
        sa.Column("permissions", JSONB(), nullable=False, server_default="[]"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="ACTIVE"),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["delegate_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_resource_delegations_resource", "resource_delegations", ["resource_id"])
    op.create_index("ix_resource_delegations_delegate", "resource_delegations", ["delegate_id"])


def downgrade() -> None:
    op.drop_table("resource_delegations")
    op.drop_table("ownership_history")
    op.drop_table("resource_shares")
    op.drop_table("resource_acl")
    op.drop_table("resources")
