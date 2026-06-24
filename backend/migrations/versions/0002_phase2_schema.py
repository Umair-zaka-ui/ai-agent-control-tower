"""Phase 2 schema: agent API keys, policies, advanced RBAC, approval
priority/SLA/comments and audit log forensic fields.

Revision ID: 0002_phase2
Revises: 0001_initial
Create Date: 2026-06-24

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_phase2"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

api_key_status = postgresql.ENUM(
    "ACTIVE", "REVOKED", name="api_key_status", create_type=False
)
approval_priority = postgresql.ENUM(
    "LOW", "MEDIUM", "HIGH", "CRITICAL", name="approval_priority", create_type=False
)

_NEW_ENUMS = (api_key_status, approval_priority)


def upgrade() -> None:
    bind = op.get_bind()
    for enum in _NEW_ENUMS:
        enum.create(bind, checkfirst=True)

    # --- agent_api_keys ---------------------------------------------------- #
    op.create_table(
        "agent_api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key_hash", sa.String(length=128), nullable=False),
        sa.Column("key_prefix", sa.String(length=20), nullable=False),
        sa.Column("status", api_key_status, nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("key_hash", name="uq_agent_api_keys_key_hash"),
    )
    op.create_index("ix_agent_api_keys_agent_id", "agent_api_keys", ["agent_id"])
    op.create_index("ix_agent_api_keys_key_hash", "agent_api_keys", ["key_hash"])

    # --- policies ---------------------------------------------------------- #
    op.create_table(
        "policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("resource", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("conditions", postgresql.JSONB(), nullable=False),
        sa.Column("decision", sa.String(length=30), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_policies_organization_id", "policies", ["organization_id"])
    op.create_index("ix_policies_resource", "policies", ["resource"])
    op.create_index("ix_policies_action", "policies", ["action"])
    op.create_index("ix_policies_enabled", "policies", ["enabled"])

    # --- RBAC: roles / rbac_permissions / role_permissions / user_roles ---- #
    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("organization_id", "name", name="uq_role_org_name"),
    )
    op.create_index("ix_roles_organization_id", "roles", ["organization_id"])

    op.create_table(
        "rbac_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.UniqueConstraint("code", name="uq_rbac_permissions_code"),
    )
    op.create_index("ix_rbac_permissions_code", "rbac_permissions", ["code"])

    op.create_table(
        "role_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["permission_id"], ["rbac_permissions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )
    op.create_index("ix_role_permissions_role_id", "role_permissions", ["role_id"])
    op.create_index("ix_role_permissions_permission_id", "role_permissions", ["permission_id"])

    op.create_table(
        "user_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_role"),
    )
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"])
    op.create_index("ix_user_roles_role_id", "user_roles", ["role_id"])

    # --- approval_comments ------------------------------------------------- #
    op.create_table(
        "approval_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("approval_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_approval_comments_approval_id", "approval_comments", ["approval_id"])

    # --- alter approvals --------------------------------------------------- #
    op.add_column(
        "approvals",
        sa.Column("priority", approval_priority, nullable=False, server_default="MEDIUM"),
    )
    op.add_column("approvals", sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_approvals_priority", "approvals", ["priority"])

    # --- alter audit_logs -------------------------------------------------- #
    op.add_column("audit_logs", sa.Column("ip_address", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("user_agent", sa.String(length=512), nullable=True))
    op.add_column("audit_logs", sa.Column("request_id", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("trace_id", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("before_state", postgresql.JSONB(), nullable=True))
    op.add_column("audit_logs", sa.Column("after_state", postgresql.JSONB(), nullable=True))
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"])
    op.create_index("ix_audit_logs_trace_id", "audit_logs", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_trace_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_request_id", table_name="audit_logs")
    for col in ("after_state", "before_state", "trace_id", "request_id", "user_agent", "ip_address"):
        op.drop_column("audit_logs", col)

    op.drop_index("ix_approvals_priority", table_name="approvals")
    op.drop_column("approvals", "sla_due_at")
    op.drop_column("approvals", "priority")

    op.drop_table("approval_comments")
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.drop_table("rbac_permissions")
    op.drop_table("roles")
    op.drop_table("policies")
    op.drop_table("agent_api_keys")

    bind = op.get_bind()
    for enum in reversed(_NEW_ENUMS):
        enum.drop(bind, checkfirst=True)
