"""Phase 4 Part 4.2.2.3.2 - enterprise password policy & credential management.

Adds:

- ``users.password_changed_at`` / ``password_expires_at`` / ``must_change_password``
  the credential lifecycle fields (SRS §11, §12, §13). All nullable/defaulted, so
  existing rows are untouched: a NULL ``password_expires_at`` means "never expires",
  which is the safe posture for accounts that predate the policy.
- ``password_history``  the last N argon2id hashes per user, so a change can refuse
  to reuse a recent password (SRS §10). Hashes only; never plaintext.
- ``credential.reset`` / ``credential.dashboard`` permissions, backfilled onto every
  existing SUPER_ADMIN and ADMIN role (as 0012 did for invitations): ``seed_rbac``
  only runs at registration, so without the backfill existing admins would 403 on
  the new admin-reset and dashboard endpoints.

Additive: no column is dropped or retyped.

Revision ID: 0013_credential_management  (<=32 chars: alembic_version.version_num is varchar(32))
Revises: 0012_registration_invites
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0013_credential_management"
down_revision: str | None = "0012_registration_invites"
branch_labels = None
depends_on = None

_PERMISSIONS = (
    ("credential.reset", "Reset another user's password and issue temporary credentials"),
    ("credential.dashboard", "View the organization password/credential dashboard"),
)
_ROLES = ("SUPER_ADMIN", "ADMIN")


def upgrade() -> None:
    # ---------------------------------------------------------------- #
    # users: credential lifecycle columns
    # ---------------------------------------------------------------- #
    op.add_column(
        "users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users", sa.Column("password_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_users_password_expires_at", "users", ["password_expires_at"]
    )

    # ---------------------------------------------------------------- #
    # password_history
    # ---------------------------------------------------------------- #
    op.create_table(
        "password_history",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_password_history_user_created", "password_history", ["user_id", "created_at"]
    )

    # ---------------------------------------------------------------- #
    # RBAC: credential permissions, backfilled onto existing admin roles
    # ---------------------------------------------------------------- #
    conn = op.get_bind()
    insert_permission = sa.text(
        """
        INSERT INTO rbac_permissions (id, code, description)
        SELECT gen_random_uuid(), :code, :description
        WHERE NOT EXISTS (SELECT 1 FROM rbac_permissions WHERE code = :code)
        """
    )
    for code, description in _PERMISSIONS:
        conn.execute(insert_permission, {"code": code, "description": description})

    conn.execute(
        sa.text(
            """
            INSERT INTO role_permissions (id, role_id, permission_id)
            SELECT gen_random_uuid(), r.id, p.id
              FROM roles r
              CROSS JOIN rbac_permissions p
             WHERE r.name = ANY(:roles)
               AND p.code = ANY(:codes)
               AND NOT EXISTS (
                     SELECT 1 FROM role_permissions rp
                      WHERE rp.role_id = r.id AND rp.permission_id = p.id
                   )
            """
        ),
        {"roles": list(_ROLES), "codes": [c for c, _ in _PERMISSIONS]},
    )


def downgrade() -> None:
    conn = op.get_bind()
    codes = [c for c, _ in _PERMISSIONS]
    conn.execute(
        sa.text(
            """
            DELETE FROM role_permissions
             WHERE permission_id IN (SELECT id FROM rbac_permissions WHERE code = ANY(:codes))
            """
        ),
        {"codes": codes},
    )
    conn.execute(sa.text("DELETE FROM rbac_permissions WHERE code = ANY(:codes)"), {"codes": codes})

    op.drop_index("ix_password_history_user_created", table_name="password_history")
    op.drop_table("password_history")
    op.drop_index("ix_users_password_expires_at", table_name="users")
    op.drop_column("users", "must_change_password")
    op.drop_column("users", "password_expires_at")
    op.drop_column("users", "password_changed_at")
