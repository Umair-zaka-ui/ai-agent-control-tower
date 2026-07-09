"""Phase 4 Part 4.2.2.3.3 - password reset, account recovery & email change.

Adds:

- ``password_reset_requests``  single-use, 30-minute, hashed reset tokens (§5).
- ``users.pending_email``       a requested-but-unconfirmed new address (§12).
- ``email_verifications.purpose`` / ``new_email``  so one table serves both account
  activation and email-change confirmation (§11, §12).
- ``recovery.view`` permission, backfilled onto every existing SUPER_ADMIN / ADMIN
  role (as prior parts did): ``seed_rbac`` only runs at registration, so without the
  backfill existing admins would 403 on the recovery dashboard.

Additive: no column is dropped or retyped. Existing ``email_verifications`` rows
default to ``purpose='ACTIVATION'`` — exactly what they already were.

Revision ID: 0014_password_reset_recovery  (<=32 chars)
Revises: 0013_credential_management
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0014_password_reset_recovery"
down_revision: str | None = "0013_credential_management"
branch_labels = None
depends_on = None

_PERMISSIONS = (
    ("recovery.view", "View password-reset and recovery events in the organization"),
)
_ROLES = ("SUPER_ADMIN", "ADMIN")


def upgrade() -> None:
    # ---------------------------------------------------------------- #
    # users.pending_email
    # ---------------------------------------------------------------- #
    op.add_column("users", sa.Column("pending_email", sa.String(length=320), nullable=True))

    # ---------------------------------------------------------------- #
    # email_verifications: purpose + new_email
    # ---------------------------------------------------------------- #
    op.add_column(
        "email_verifications",
        sa.Column("purpose", sa.String(length=20), nullable=False, server_default="ACTIVATION"),
    )
    op.add_column(
        "email_verifications", sa.Column("new_email", sa.String(length=320), nullable=True)
    )

    # ---------------------------------------------------------------- #
    # password_reset_requests
    # ---------------------------------------------------------------- #
    op.create_table(
        "password_reset_requests",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_ip", sa.String(length=64), nullable=True),
        sa.Column("created_user_agent", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_requests_token_hash"),
    )
    op.create_index("ix_password_reset_requests_user_id", "password_reset_requests", ["user_id"])
    op.create_index(
        "ix_password_reset_requests_organization_id", "password_reset_requests", ["organization_id"]
    )
    op.create_index(
        "ix_password_reset_requests_token_hash", "password_reset_requests", ["token_hash"]
    )
    op.create_index("ix_password_reset_requests_status", "password_reset_requests", ["status"])
    op.create_index(
        "ix_password_reset_requests_user_status", "password_reset_requests", ["user_id", "status"]
    )

    # ---------------------------------------------------------------- #
    # RBAC: recovery.view, backfilled onto existing admin roles
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

    op.drop_index("ix_password_reset_requests_user_status", table_name="password_reset_requests")
    op.drop_index("ix_password_reset_requests_status", table_name="password_reset_requests")
    op.drop_index("ix_password_reset_requests_token_hash", table_name="password_reset_requests")
    op.drop_index(
        "ix_password_reset_requests_organization_id", table_name="password_reset_requests"
    )
    op.drop_index("ix_password_reset_requests_user_id", table_name="password_reset_requests")
    op.drop_table("password_reset_requests")
    op.drop_column("email_verifications", "new_email")
    op.drop_column("email_verifications", "purpose")
    op.drop_column("users", "pending_email")
