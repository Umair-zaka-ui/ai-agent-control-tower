"""Phase 4 Part 4.1 - Enterprise Identity Platform foundation.

Additive identity schema. Reuses the existing users/organizations/roles tables
and adds the new identity entities: departments, teams, service_accounts,
external_clients, agent_identities, sessions, refresh_tokens, device_sessions,
security_events. Also adds a nullable ``users.department_id`` for the
organization → department → user hierarchy.

Revision ID: 0006_identity_foundation
Revises: 0005_approval_workbench
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_identity_foundation"
down_revision: str | None = "0005_approval_workbench"
branch_labels = None
depends_on = None


def _uuid_pk() -> sa.Column:
    return sa.Column("id", sa.UUID(), primary_key=True)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "departments",
        _uuid_pk(),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("manager_id", sa.UUID(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["manager_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_departments_organization_id", "departments", ["organization_id"])

    op.create_table(
        "teams",
        _uuid_pk(),
        sa.Column("department_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("lead_id", sa.UUID(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_teams_department_id", "teams", ["department_id"])

    op.create_table(
        "service_accounts",
        _uuid_pk(),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("client_secret_hash", sa.String(length=255), nullable=False),
        sa.Column("permissions", postgresql.JSONB(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_service_accounts_organization_id", "service_accounts", ["organization_id"])

    op.create_table(
        "external_clients",
        _uuid_pk(),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("client_name", sa.String(length=255), nullable=False),
        sa.Column("client_id", sa.String(length=100), nullable=False),
        sa.Column("redirect_uri", sa.String(length=2048), nullable=True),
        sa.Column("secret_hash", sa.String(length=255), nullable=False),
        sa.Column("allowed_scopes", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("client_id", name="uq_external_clients_client_id"),
    )
    op.create_index("ix_external_clients_organization_id", "external_clients", ["organization_id"])
    op.create_index("ix_external_clients_client_id", "external_clients", ["client_id"])

    op.create_table(
        "agent_identities",
        _uuid_pk(),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.String(length=100), nullable=False),
        sa.Column("credential_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("client_id", name="uq_agent_identities_client_id"),
    )
    op.create_index("ix_agent_identities_agent_id", "agent_identities", ["agent_id"])
    op.create_index("ix_agent_identities_client_id", "agent_identities", ["client_id"])

    op.create_table(
        "sessions",
        _uuid_pk(),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "refresh_tokens",
        _uuid_pk(),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_to_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"])

    op.create_table(
        "device_sessions",
        _uuid_pk(),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("device_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("device_label", sa.String(length=255), nullable=True),
        sa.Column("trusted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_device_sessions_user_id", "device_sessions", ["user_id"])
    op.create_index("ix_device_sessions_fingerprint", "device_sessions", ["device_fingerprint"])

    op.create_table(
        "security_events",
        _uuid_pk(),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_type", sa.String(length=30), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("target_type", sa.String(length=30), nullable=True),
        sa.Column("target_id", sa.UUID(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("meta", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_security_events_organization_id", "security_events", ["organization_id"])
    op.create_index("ix_security_events_event_type", "security_events", ["event_type"])
    op.create_index("ix_security_events_request_id", "security_events", ["request_id"])

    # Hierarchy link on the existing users table (nullable, non-breaking).
    op.add_column("users", sa.Column("department_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_users_department_id", "users", "departments", ["department_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_users_department_id", "users", ["department_id"])


def downgrade() -> None:
    op.drop_index("ix_users_department_id", table_name="users")
    op.drop_constraint("fk_users_department_id", "users", type_="foreignkey")
    op.drop_column("users", "department_id")

    op.drop_table("security_events")
    op.drop_table("device_sessions")
    op.drop_table("refresh_tokens")
    op.drop_table("sessions")
    op.drop_table("agent_identities")
    op.drop_table("external_clients")
    op.drop_table("service_accounts")
    op.drop_table("teams")
    op.drop_table("departments")
