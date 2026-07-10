"""Phase 4.3.1 - Enterprise RBAC foundation.

Extends the existing flat RBAC (roles / rbac_permissions / role_permissions /
user_roles) with enterprise metadata and adds three tables:

- ``permission_groups``     domain grouping for the permission catalog (§12).
- ``role_hierarchy``        acyclic parent->child role inheritance edges (§17).
- ``authorization_audit``   decision + change audit trail (§10, §23).

Column additions (all with safe server defaults so existing rows stay valid):

- ``roles``            display_name, category, status, is_assignable, priority,
                       created_by, updated_by (§8, §9, §10, §16).
- ``rbac_permissions`` display_name, group_id, resource_type, action, is_system,
                       created_at (§10, §11, §12).
- ``role_permissions`` created_at.
- ``user_roles``       scope, organization_id, department_id, team_id, project_id,
                       resource_type, resource_id, expires_at, assigned_by,
                       created_at (§14, §15) + a wider uniqueness constraint.

Data (groups, permission enrichment, the built-in role taxonomy and hierarchy)
is seeded idempotently by ``app.authorization.seeding.seed_authorization`` rather
than in raw SQL here.

Additive: no column is dropped or retyped.

Revision ID: 0016_rbac_foundation
Revises: 0015_account_protection
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_rbac_foundation"
down_revision: str | None = "0015_account_protection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- permission_groups (new) ------------------------------------- #
    op.create_table(
        "permission_groups",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("name", name="uq_permission_group_name"),
    )
    op.create_index("ix_permission_groups_name", "permission_groups", ["name"])

    # ---- roles: enterprise metadata ---------------------------------- #
    op.add_column("roles", sa.Column("display_name", sa.String(length=150), nullable=True))
    op.add_column("roles", sa.Column("category", sa.String(length=20), nullable=False,
                                     server_default="CUSTOM"))
    op.add_column("roles", sa.Column("status", sa.String(length=20), nullable=False,
                                     server_default="ACTIVE"))
    op.add_column("roles", sa.Column("is_assignable", sa.Boolean(), nullable=False,
                                     server_default=sa.true()))
    op.add_column("roles", sa.Column("priority", sa.Integer(), nullable=False,
                                     server_default="50"))
    op.add_column("roles", sa.Column("created_by", sa.UUID(), nullable=True))
    op.add_column("roles", sa.Column("updated_by", sa.UUID(), nullable=True))
    op.create_index("ix_roles_status", "roles", ["status"])
    op.create_foreign_key("fk_roles_created_by", "roles", "users",
                          ["created_by"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_roles_updated_by", "roles", "users",
                          ["updated_by"], ["id"], ondelete="SET NULL")
    # Existing system roles are SYSTEM category.
    op.execute("UPDATE roles SET category = 'SYSTEM' WHERE is_system = true")
    op.execute("UPDATE roles SET display_name = name WHERE display_name IS NULL")

    # ---- rbac_permissions: catalog metadata -------------------------- #
    op.add_column("rbac_permissions", sa.Column("display_name", sa.String(length=150), nullable=True))
    op.add_column("rbac_permissions", sa.Column("group_id", sa.UUID(), nullable=True))
    op.add_column("rbac_permissions", sa.Column("resource_type", sa.String(length=50), nullable=True))
    op.add_column("rbac_permissions", sa.Column("action", sa.String(length=50), nullable=True))
    op.add_column("rbac_permissions", sa.Column("is_system", sa.Boolean(), nullable=False,
                                                server_default=sa.true()))
    op.add_column("rbac_permissions", sa.Column("created_at", sa.DateTime(timezone=True),
                                                nullable=False, server_default=sa.func.now()))
    op.create_index("ix_rbac_permissions_group_id", "rbac_permissions", ["group_id"])
    op.create_index("ix_rbac_permissions_resource_type", "rbac_permissions", ["resource_type"])
    op.create_foreign_key("fk_rbac_permissions_group_id", "rbac_permissions", "permission_groups",
                          ["group_id"], ["id"], ondelete="SET NULL")
    # Derive resource_type/action from the dotted code for existing rows.
    op.execute("UPDATE rbac_permissions SET resource_type = split_part(code, '.', 1) "
               "WHERE resource_type IS NULL")
    op.execute("UPDATE rbac_permissions SET action = NULLIF(split_part(code, '.', 2), '') "
               "WHERE action IS NULL")

    # ---- role_permissions: created_at -------------------------------- #
    op.add_column("role_permissions", sa.Column("created_at", sa.DateTime(timezone=True),
                                                nullable=False, server_default=sa.func.now()))

    # ---- user_roles: scoped assignment ------------------------------- #
    op.add_column("user_roles", sa.Column("scope", sa.String(length=20), nullable=False,
                                          server_default="GLOBAL"))
    op.add_column("user_roles", sa.Column("organization_id", sa.UUID(), nullable=True))
    op.add_column("user_roles", sa.Column("department_id", sa.UUID(), nullable=True))
    op.add_column("user_roles", sa.Column("team_id", sa.UUID(), nullable=True))
    op.add_column("user_roles", sa.Column("project_id", sa.UUID(), nullable=True))
    op.add_column("user_roles", sa.Column("resource_type", sa.String(length=50), nullable=True))
    op.add_column("user_roles", sa.Column("resource_id", sa.UUID(), nullable=True))
    op.add_column("user_roles", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("user_roles", sa.Column("assigned_by", sa.UUID(), nullable=True))
    op.add_column("user_roles", sa.Column("created_at", sa.DateTime(timezone=True),
                                          nullable=False, server_default=sa.func.now()))
    op.create_index("ix_user_roles_scope", "user_roles", ["scope"])
    op.create_index("ix_user_roles_organization_id", "user_roles", ["organization_id"])
    op.create_foreign_key("fk_user_roles_organization_id", "user_roles", "organizations",
                          ["organization_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_user_roles_department_id", "user_roles", "departments",
                          ["department_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_user_roles_team_id", "user_roles", "teams",
                          ["team_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_user_roles_assigned_by", "user_roles", "users",
                          ["assigned_by"], ["id"], ondelete="SET NULL")
    # Widen uniqueness from (user, role) to include the scope key.
    op.drop_constraint("uq_user_role", "user_roles", type_="unique")
    op.create_unique_constraint(
        "uq_user_role_scope", "user_roles",
        ["user_id", "role_id", "scope", "organization_id", "department_id",
         "team_id", "project_id", "resource_type", "resource_id"],
    )

    # ---- role_hierarchy (new) ---------------------------------------- #
    op.create_table(
        "role_hierarchy",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("parent_role_id", sa.UUID(), nullable=False),
        sa.Column("child_role_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["parent_role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["child_role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("parent_role_id", "child_role_id", name="uq_role_hierarchy_edge"),
    )
    op.create_index("ix_role_hierarchy_parent", "role_hierarchy", ["parent_role_id"])
    op.create_index("ix_role_hierarchy_child", "role_hierarchy", ["child_role_id"])

    # ---- authorization_audit (new) ----------------------------------- #
    op.create_table(
        "authorization_audit",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("identity_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("permission", sa.String(length=100), nullable=True),
        sa.Column("resource_type", sa.String(length=50), nullable=True),
        sa.Column("resource_id", sa.UUID(), nullable=True),
        sa.Column("decision", sa.String(length=10), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("meta", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_authorization_audit_org", "authorization_audit", ["organization_id"])
    op.create_index("ix_authorization_audit_actor", "authorization_audit", ["actor_id"])
    op.create_index("ix_authorization_audit_identity", "authorization_audit", ["identity_id"])
    op.create_index("ix_authorization_audit_event_type", "authorization_audit", ["event_type"])
    op.create_index("ix_authorization_audit_created_at", "authorization_audit", ["created_at"])


def downgrade() -> None:
    op.drop_table("authorization_audit")
    op.drop_table("role_hierarchy")

    op.drop_constraint("uq_user_role_scope", "user_roles", type_="unique")
    op.create_unique_constraint("uq_user_role", "user_roles", ["user_id", "role_id"])
    for fk in ("fk_user_roles_assigned_by", "fk_user_roles_team_id",
               "fk_user_roles_department_id", "fk_user_roles_organization_id"):
        op.drop_constraint(fk, "user_roles", type_="foreignkey")
    op.drop_index("ix_user_roles_organization_id", table_name="user_roles")
    op.drop_index("ix_user_roles_scope", table_name="user_roles")
    for col in ("created_at", "assigned_by", "expires_at", "resource_id", "resource_type",
                "project_id", "team_id", "department_id", "organization_id", "scope"):
        op.drop_column("user_roles", col)

    op.drop_column("role_permissions", "created_at")

    op.drop_constraint("fk_rbac_permissions_group_id", "rbac_permissions", type_="foreignkey")
    op.drop_index("ix_rbac_permissions_resource_type", table_name="rbac_permissions")
    op.drop_index("ix_rbac_permissions_group_id", table_name="rbac_permissions")
    for col in ("created_at", "is_system", "action", "resource_type", "group_id", "display_name"):
        op.drop_column("rbac_permissions", col)

    op.drop_constraint("fk_roles_updated_by", "roles", type_="foreignkey")
    op.drop_constraint("fk_roles_created_by", "roles", type_="foreignkey")
    op.drop_index("ix_roles_status", table_name="roles")
    for col in ("updated_by", "created_by", "priority", "is_assignable", "status",
                "category", "display_name"):
        op.drop_column("roles", col)

    op.drop_index("ix_permission_groups_name", table_name="permission_groups")
    op.drop_table("permission_groups")
