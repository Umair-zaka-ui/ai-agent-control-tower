"""Phase 4.3.3 - Enterprise organization authorization hierarchy.

Extends the existing tenant model with the full enterprise hierarchy:
Platform → Organization → Business Unit → Department → Team → Project → Resources.

- ``organizations``     + slug, owner_id (§5).
- ``business_units``    new (§11).
- ``departments``       + business_unit_id, status (kept organization_id).
- ``teams``             + status (already has department_id, lead_id).
- ``projects``          new (§11).
- ``resource_ownership`` new — a resource's full org path + owner (§6, §11).
- ``delegations``       new — delegated administration over a scope (§10).

Additive: no column dropped or retyped.

Revision ID: 0018_org_hierarchy
Revises: 0017_permission_engine
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0018_org_hierarchy"
down_revision: str | None = "0017_permission_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- organizations: slug + owner ---------------------------------- #
    op.add_column("organizations", sa.Column("slug", sa.String(length=120), nullable=True))
    op.add_column("organizations", sa.Column("owner_id", sa.UUID(), nullable=True))
    op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)
    op.create_foreign_key("fk_organizations_owner_id", "organizations", "users",
                          ["owner_id"], ["id"], ondelete="SET NULL")

    # ---- business_units (new) ----------------------------------------- #
    op.create_table(
        "business_units",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("manager_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["manager_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("organization_id", "name", name="uq_business_unit_org_name"),
    )
    op.create_index("ix_business_units_org", "business_units", ["organization_id"])

    # ---- departments: business_unit_id + status ----------------------- #
    op.add_column("departments", sa.Column("business_unit_id", sa.UUID(), nullable=True))
    op.add_column("departments", sa.Column("status", sa.String(length=20), nullable=False,
                                           server_default="ACTIVE"))
    op.create_index("ix_departments_business_unit", "departments", ["business_unit_id"])
    op.create_foreign_key("fk_departments_business_unit_id", "departments", "business_units",
                          ["business_unit_id"], ["id"], ondelete="SET NULL")

    # ---- teams: status ------------------------------------------------ #
    op.add_column("teams", sa.Column("status", sa.String(length=20), nullable=False,
                                     server_default="ACTIVE"))

    # ---- projects (new) ----------------------------------------------- #
    op.create_table(
        "projects",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("team_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("team_id", "name", name="uq_project_team_name"),
    )
    op.create_index("ix_projects_team", "projects", ["team_id"])

    # ---- resource_ownership (new) ------------------------------------- #
    op.create_table(
        "resource_ownership",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("resource_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("business_unit_id", sa.UUID(), nullable=True),
        sa.Column("department_id", sa.UUID(), nullable=True),
        sa.Column("team_id", sa.UUID(), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("resource_type", "resource_id", name="uq_resource_ownership"),
    )
    op.create_index("ix_resource_ownership_org", "resource_ownership", ["organization_id"])
    op.create_index("ix_resource_ownership_lookup", "resource_ownership",
                    ["resource_type", "resource_id"])

    # ---- delegations (new) -------------------------------------------- #
    op.create_table(
        "delegations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("delegator_id", sa.UUID(), nullable=True),
        sa.Column("delegatee_id", sa.UUID(), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.UUID(), nullable=True),
        sa.Column("permission", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["delegatee_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_delegations_delegatee", "delegations", ["delegatee_id"])
    op.create_index("ix_delegations_org", "delegations", ["organization_id"])


def downgrade() -> None:
    op.drop_table("delegations")
    op.drop_table("resource_ownership")
    op.drop_table("projects")
    op.drop_column("teams", "status")
    op.drop_constraint("fk_departments_business_unit_id", "departments", type_="foreignkey")
    op.drop_index("ix_departments_business_unit", table_name="departments")
    op.drop_column("departments", "status")
    op.drop_column("departments", "business_unit_id")
    op.drop_table("business_units")
    op.drop_constraint("fk_organizations_owner_id", "organizations", type_="foreignkey")
    op.drop_index("ix_organizations_slug", table_name="organizations")
    op.drop_column("organizations", "owner_id")
    op.drop_column("organizations", "slug")
