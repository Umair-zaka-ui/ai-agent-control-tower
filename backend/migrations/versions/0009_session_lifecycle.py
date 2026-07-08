"""Phase 4 Part 4.2.2.2 - login, logout & session lifecycle.

Turns the thin ``sessions`` table into the enterprise ``auth_sessions`` aggregate
(SRS §6), adds ``auth_devices`` (§13), and promotes the refresh-token family to a
first-class column (§7).

Structure:

1. ``auth_devices``  — new table.
2. ``sessions`` → ``auth_sessions``, renamed and widened. Existing rows are
   preserved and backfilled: every live session gets deadlines derived from its
   own ``created_at``/``expires_at`` and a freshly minted family id.
3. ``refresh_tokens`` gains ``family_id`` + ``reuse_detected_at``. Existing tokens
   inherit their session's new family id, so rotation chains survive the upgrade.
4. ``device_sessions`` is dropped. It was declared in Phase 4.2.1 but never read
   or written by any code path, and ``auth_devices`` supersedes it.

Rename-in-place (rather than create-new + copy) keeps live sessions valid across
the deploy: a user does not get logged out by this migration.

Revision ID: 0009_session_lifecycle
Revises: 0008_auth_login_history
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0009_session_lifecycle"
down_revision: str | None = "0008_auth_login_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------------------------------------------------------- #
    # 1. Devices (SRS §13)
    # ---------------------------------------------------------------- #
    op.create_table(
        "auth_devices",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("fingerprint", sa.String(length=128), nullable=False),
        sa.Column("device_name", sa.String(length=255), nullable=True),
        sa.Column("device_type", sa.String(length=32), nullable=True),
        sa.Column("browser", sa.String(length=64), nullable=True),
        sa.Column("browser_version", sa.String(length=32), nullable=True),
        sa.Column("operating_system", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="UNKNOWN"),
        sa.Column("last_ip", sa.String(length=64), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_auth_devices_user_id", "auth_devices", ["user_id"])
    op.create_index("ix_auth_devices_fingerprint", "auth_devices", ["fingerprint"])
    op.create_index("ix_auth_devices_status", "auth_devices", ["status"])
    # One device row per (user, fingerprint): registration is an upsert.
    op.create_unique_constraint(
        "uq_auth_devices_user_fingerprint", "auth_devices", ["user_id", "fingerprint"]
    )

    # ---------------------------------------------------------------- #
    # 2. sessions -> auth_sessions (SRS §6)
    # ---------------------------------------------------------------- #
    op.rename_table("sessions", "auth_sessions")

    op.add_column("auth_sessions", sa.Column("organization_id", sa.UUID(), nullable=True))
    op.add_column(
        "auth_sessions",
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
    )
    op.add_column("auth_sessions", sa.Column("device_id", sa.UUID(), nullable=True))
    op.add_column("auth_sessions", sa.Column("device_name", sa.String(length=255), nullable=True))
    op.add_column("auth_sessions", sa.Column("device_type", sa.String(length=32), nullable=True))
    op.add_column("auth_sessions", sa.Column("browser", sa.String(length=64), nullable=True))
    op.add_column(
        "auth_sessions", sa.Column("browser_version", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "auth_sessions", sa.Column("operating_system", sa.String(length=64), nullable=True)
    )
    op.add_column("auth_sessions", sa.Column("country", sa.String(length=64), nullable=True))
    op.add_column("auth_sessions", sa.Column("city", sa.String(length=128), nullable=True))
    op.add_column("auth_sessions", sa.Column("timezone", sa.String(length=64), nullable=True))
    op.add_column("auth_sessions", sa.Column("login_method", sa.String(length=32), nullable=True))
    op.add_column(
        "auth_sessions", sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "auth_sessions", sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "auth_sessions",
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("auth_sessions", sa.Column("revoked_reason", sa.String(length=32), nullable=True))
    op.add_column(
        "auth_sessions",
        sa.Column("security_score", sa.Integer(), nullable=False, server_default="100"),
    )
    op.add_column(
        "auth_sessions",
        sa.Column("is_trusted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("auth_sessions", sa.Column("refresh_token_family_id", sa.UUID(), nullable=True))

    # Backfill existing rows so the NOT NULL constraints below can be applied.
    #   - absolute deadline: the old ``expires_at`` was exactly this concept
    #   - idle deadline:     seed from last activity we know about
    #   - family:            one fresh family per existing session
    #   - status:            derive from ``revoked_at`` so nothing silently
    #                        re-activates a session an admin already revoked
    op.execute(
        """
        UPDATE auth_sessions SET
            last_activity_at    = COALESCE(last_activity_at, last_seen_at, created_at),
            absolute_expires_at = COALESCE(absolute_expires_at, expires_at),
            idle_expires_at     = COALESCE(
                idle_expires_at,
                COALESCE(last_seen_at, created_at) + INTERVAL '30 minutes'
            ),
            refresh_token_family_id = COALESCE(refresh_token_family_id, gen_random_uuid()),
            organization_id = COALESCE(
                organization_id, (SELECT u.organization_id FROM users u WHERE u.id = user_id)
            ),
            status = CASE WHEN revoked_at IS NOT NULL THEN 'REVOKED' ELSE 'ACTIVE' END,
            revoked_reason = CASE WHEN revoked_at IS NOT NULL THEN 'USER_LOGOUT' ELSE NULL END
        """
    )

    op.alter_column("auth_sessions", "idle_expires_at", nullable=False)
    op.alter_column("auth_sessions", "absolute_expires_at", nullable=False)
    op.alter_column("auth_sessions", "refresh_token_family_id", nullable=False)

    # ``expires_at`` is superseded by ``absolute_expires_at``.
    op.drop_column("auth_sessions", "expires_at")

    op.create_foreign_key(
        "fk_auth_sessions_organization_id",
        "auth_sessions",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_auth_sessions_device_id",
        "auth_sessions",
        "auth_devices",
        ["device_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_auth_sessions_status", "auth_sessions", ["status"])
    op.create_index("ix_auth_sessions_organization_id", "auth_sessions", ["organization_id"])
    op.create_index("ix_auth_sessions_device_id", "auth_sessions", ["device_id"])
    op.create_index(
        "ix_auth_sessions_family", "auth_sessions", ["refresh_token_family_id"]
    )
    # The hot path is "load one active session by id" — covered by the PK — and
    # "list active sessions for a user", covered here.
    op.create_index("ix_auth_sessions_user_status", "auth_sessions", ["user_id", "status"])

    # ---------------------------------------------------------------- #
    # 3. refresh_tokens: first-class families (SRS §7)
    # ---------------------------------------------------------------- #
    op.add_column("refresh_tokens", sa.Column("family_id", sa.UUID(), nullable=True))
    op.add_column(
        "refresh_tokens", sa.Column("reuse_detected_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        """
        UPDATE refresh_tokens rt
           SET family_id = s.refresh_token_family_id
          FROM auth_sessions s
         WHERE rt.session_id = s.id AND rt.family_id IS NULL
        """
    )
    # Any orphan token (session already hard-deleted) gets its own family.
    op.execute("UPDATE refresh_tokens SET family_id = gen_random_uuid() WHERE family_id IS NULL")
    op.alter_column("refresh_tokens", "family_id", nullable=False)
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])

    # ---------------------------------------------------------------- #
    # 4. Drop the never-used device_sessions table
    # ---------------------------------------------------------------- #
    op.drop_table("device_sessions")


def downgrade() -> None:
    op.create_table(
        "device_sessions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("device_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("device_label", sa.String(length=255), nullable=True),
        sa.Column("trusted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "reuse_detected_at")
    op.drop_column("refresh_tokens", "family_id")

    op.add_column("auth_sessions", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE auth_sessions SET expires_at = absolute_expires_at")
    op.alter_column("auth_sessions", "expires_at", nullable=False)

    op.drop_index("ix_auth_sessions_user_status", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_family", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_device_id", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_organization_id", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_status", table_name="auth_sessions")
    op.drop_constraint("fk_auth_sessions_device_id", "auth_sessions", type_="foreignkey")
    op.drop_constraint("fk_auth_sessions_organization_id", "auth_sessions", type_="foreignkey")

    for column in (
        "refresh_token_family_id",
        "is_trusted",
        "security_score",
        "revoked_reason",
        "absolute_expires_at",
        "idle_expires_at",
        "last_activity_at",
        "login_method",
        "timezone",
        "city",
        "country",
        "operating_system",
        "browser_version",
        "browser",
        "device_type",
        "device_name",
        "device_id",
        "status",
        "organization_id",
    ):
        op.drop_column("auth_sessions", column)

    op.rename_table("auth_sessions", "sessions")

    op.drop_index("ix_auth_devices_status", table_name="auth_devices")
    op.drop_index("ix_auth_devices_fingerprint", table_name="auth_devices")
    op.drop_index("ix_auth_devices_user_id", table_name="auth_devices")
    op.drop_table("auth_devices")
