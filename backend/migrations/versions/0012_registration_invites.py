"""Phase 4 Part 4.2.2.3.1 - enterprise registration, invitations & email verification.

Adds:

- ``invitations``          one live invitation per (org, email), enforced by a
                           *partial* unique index on PENDING rows only, so a fresh
                           invitation is allowed after cancellation or expiry.
- ``email_verifications``  single-use, hashed, 24h tokens.
- ``user_profiles``        profile data kept out of the security record ``users``.
- ``rate_limit_hits``      Postgres-backed fixed-window counter (§19). No Redis:
                           ADR-0002 makes PostgreSQL the sole datastore.
- ``organizations.registration_mode``  INVITE_ONLY (default) / ADMIN_ONLY / SELF_SERVICE.
- ``invitation.view`` / ``invitation.manage`` permissions, backfilled onto every
  existing SUPER_ADMIN and ADMIN role. ``seed_rbac`` only runs at registration, so
  without the backfill existing admins would get a 403 from the new endpoints.

Additive: no existing column is dropped or retyped. Existing organizations default
to INVITE_ONLY, which is the safe posture — an upgrade must never silently open
public registration.

Revision ID: 0012_registration_invites  (<=32 chars: alembic_version.version_num is varchar(32))
Revises: 0011_security_event_read_indexes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0012_registration_invites"
down_revision: str | None = "0011_security_event_read_indexes"
branch_labels = None
depends_on = None

_PERMISSIONS = (
    ("invitation.view", "View pending invitations in the organization"),
    ("invitation.manage", "Create, resend and cancel invitations"),
)
_ROLES = ("SUPER_ADMIN", "ADMIN")


def upgrade() -> None:
    # ---------------------------------------------------------------- #
    # organizations.registration_mode
    # ---------------------------------------------------------------- #
    op.add_column(
        "organizations",
        sa.Column(
            "registration_mode",
            sa.String(length=20),
            nullable=False,
            server_default="INVITE_ONLY",
        ),
    )

    # ---------------------------------------------------------------- #
    # invitations
    # ---------------------------------------------------------------- #
    op.create_table(
        "invitations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role_id", sa.UUID(), nullable=True),
        sa.Column("department_id", sa.UUID(), nullable=True),
        sa.Column("team_id", sa.UUID(), nullable=True),
        sa.Column("invited_by", sa.UUID(), nullable=True),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("token_hash", name="uq_invitations_token_hash"),
    )
    op.create_index("ix_invitations_organization_id", "invitations", ["organization_id"])
    op.create_index("ix_invitations_email", "invitations", ["email"])
    op.create_index("ix_invitations_token_hash", "invitations", ["token_hash"])
    op.create_index("ix_invitations_status", "invitations", ["status"])
    op.create_index("ix_invitations_org_status", "invitations", ["organization_id", "status"])
    # One *live* invitation per address per org. Case-insensitive, because
    # "Ada@x.com" and "ada@x.com" are the same mailbox to every mail server.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_invitations_pending_email
            ON invitations (organization_id, lower(email))
         WHERE status = 'PENDING'
        """
    )

    # ---------------------------------------------------------------- #
    # email_verifications
    # ---------------------------------------------------------------- #
    op.create_table(
        "email_verifications",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("verification_token_hash", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("verification_token_hash", name="uq_email_verifications_token_hash"),
    )
    op.create_index("ix_email_verifications_user_id", "email_verifications", ["user_id"])
    op.create_index(
        "ix_email_verifications_token_hash", "email_verifications", ["verification_token_hash"]
    )

    # ---------------------------------------------------------------- #
    # user_profiles
    # ---------------------------------------------------------------- #
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=True),
        sa.Column("last_name", sa.String(length=100), nullable=True),
        sa.Column("job_title", sa.String(length=150), nullable=True),
        sa.Column("department", sa.String(length=150), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_user_profiles_user_id"),
    )
    op.create_index("ix_user_profiles_user_id", "user_profiles", ["user_id"])

    # ---------------------------------------------------------------- #
    # rate_limit_hits
    # ---------------------------------------------------------------- #
    op.create_table(
        "rate_limit_hits",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("bucket", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index(
        "ix_rate_limit_hits_bucket_created", "rate_limit_hits", ["bucket", "created_at"]
    )

    # ---------------------------------------------------------------- #
    # RBAC: invitation permissions, backfilled onto existing admin roles
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

    op.drop_index("ix_rate_limit_hits_bucket_created", table_name="rate_limit_hits")
    op.drop_table("rate_limit_hits")
    op.drop_index("ix_user_profiles_user_id", table_name="user_profiles")
    op.drop_table("user_profiles")
    op.drop_index("ix_email_verifications_token_hash", table_name="email_verifications")
    op.drop_index("ix_email_verifications_user_id", table_name="email_verifications")
    op.drop_table("email_verifications")
    op.execute("DROP INDEX IF EXISTS uq_invitations_pending_email")
    op.drop_index("ix_invitations_org_status", table_name="invitations")
    op.drop_index("ix_invitations_status", table_name="invitations")
    op.drop_index("ix_invitations_token_hash", table_name="invitations")
    op.drop_index("ix_invitations_email", table_name="invitations")
    op.drop_index("ix_invitations_organization_id", table_name="invitations")
    op.drop_table("invitations")
    op.drop_column("organizations", "registration_mode")
