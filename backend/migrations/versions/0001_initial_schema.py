"""Initial schema: organizations, users, agents, permissions, agent_actions,
approvals and audit_logs.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-23

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Enum types are created explicitly so upgrade/downgrade are fully reversible.
user_role = postgresql.ENUM(
    "SUPER_ADMIN", "ADMIN", "REVIEWER", "VIEWER", name="user_role", create_type=False
)
agent_status = postgresql.ENUM(
    "ACTIVE", "INACTIVE", "SUSPENDED", name="agent_status", create_type=False
)
action_decision = postgresql.ENUM(
    "ALLOW", "BLOCK", "PENDING_APPROVAL", name="action_decision", create_type=False
)
action_status = postgresql.ENUM(
    "CREATED", "APPROVED", "REJECTED", "EXECUTED", "BLOCKED",
    name="action_status", create_type=False,
)
approval_decision = postgresql.ENUM(
    "PENDING", "APPROVED", "REJECTED", name="approval_decision", create_type=False
)
actor_type = postgresql.ENUM(
    "USER", "AGENT", "SYSTEM", name="actor_type", create_type=False
)

_ALL_ENUMS = (
    user_role,
    agent_status,
    action_decision,
    action_status,
    approval_decision,
    actor_type,
)

_TIMESTAMP = lambda: sa.DateTime(timezone=True)  # noqa: E731


def upgrade() -> None:
    bind = op.get_bind()
    for enum in _ALL_ENUMS:
        enum.create(bind, checkfirst=True)

    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", _TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", _TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", _TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", _TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_users_organization_id", "users", ["organization_id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("agent_type", sa.String(length=100), nullable=False),
        sa.Column("api_key_hash", sa.String(length=255), nullable=False),
        sa.Column("status", agent_status, nullable=False),
        sa.Column("created_at", _TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", _TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agents_organization_id", "agents", ["organization_id"])

    op.create_table(
        "permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("created_at", _TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", _TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "agent_id", "resource", "action", name="uq_permission_agent_resource_action"
        ),
    )
    op.create_index("ix_permissions_organization_id", "permissions", ["organization_id"])
    op.create_index("ix_permissions_agent_id", "permissions", ["agent_id"])

    op.create_table(
        "agent_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("input_payload", postgresql.JSONB(), nullable=False),
        sa.Column("output_payload", postgresql.JSONB(), nullable=True),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.Column("decision", action_decision, nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=False),
        sa.Column("status", action_status, nullable=False),
        sa.Column("created_at", _TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", _TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_actions_organization_id", "agent_actions", ["organization_id"])
    op.create_index("ix_agent_actions_agent_id", "agent_actions", ["agent_id"])

    op.create_table(
        "approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_action_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by_agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reviewed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decision", approval_decision, nullable=False),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("created_at", _TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.Column("reviewed_at", _TIMESTAMP(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_action_id"], ["agent_actions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("agent_action_id", name="uq_approvals_agent_action_id"),
    )
    op.create_index("ix_approvals_organization_id", "approvals", ["organization_id"])
    op.create_index("ix_approvals_agent_action_id", "approvals", ["agent_action_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_type", actor_type, nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", _TIMESTAMP(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_audit_logs_organization_id", "audit_logs", ["organization_id"])
    op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"])
    op.create_index("ix_audit_logs_entity_type", "audit_logs", ["entity_type"])
    op.create_index("ix_audit_logs_entity_id", "audit_logs", ["entity_id"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("approvals")
    op.drop_table("agent_actions")
    op.drop_table("permissions")
    op.drop_table("agents")
    op.drop_table("users")
    op.drop_table("organizations")

    bind = op.get_bind()
    for enum in reversed(_ALL_ENUMS):
        enum.drop(bind, checkfirst=True)
