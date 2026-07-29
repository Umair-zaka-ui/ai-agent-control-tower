"""Phase 5.7a.5 - Per-Organization Provider Credentials.

New table `provider_credentials` (`ACT-MDL-FR-080..083`): one row per
`(organization_id, provider)`, `encrypted_secret` a Fernet ciphertext
(`app/runtime/providers/credential_crypto.py`) -- never plaintext.
`secret_hint` is a masked last-four-characters string for UI display,
never enough to reconstruct the value. `base_url` is an optional per-
organization endpoint override, alongside the credential rather than in a
separate table, since an org configuring its own key for a self-hosted
gateway will usually also need to point at that gateway's own URL.

Two new RBAC permissions (`runtime.provider.view`/`runtime.provider.
manage`), registered here as global catalog rows -- following the exact,
established precedent of every other runtime-domain permission added in
this codebase (`ACT-MDL-FR-*` phases so far): added to the global
`rbac_permissions` catalog only, no per-organization role backfill via
migration (matching migration `0027_version_signing`'s handling of
`runtime.signing.view`/`.manage`, not migration `0013`'s older backfill
pattern) -- `seed_rbac`'s existing per-organization sync picks up new
catalog rows the next time it runs for a given organization.

Additive: no column is dropped or retyped.

Revision ID: 0029_provider_credentials  (<=32 chars: alembic_version.version_num is varchar(32))
Revises: 0028_streaming_and_pricing
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0029_provider_credentials"
down_revision: str | None = "0028_streaming_and_pricing"
branch_labels = None
depends_on = None

_PERMISSIONS = (
    ("runtime.provider.view", "View configured model-provider credentials (metadata and hint only, never the value)"),
    ("runtime.provider.manage", "Configure, replace, delete and test model-provider credentials"),
)
_ROLES = ("SUPER_ADMIN", "ADMIN")


def upgrade() -> None:
    op.create_table(
        "provider_credentials",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("secret_hint", sa.String(length=8), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("organization_id", "provider", name="uq_provider_credentials_org_provider"),
    )
    op.create_index("ix_provider_credentials_organization_id", "provider_credentials", ["organization_id"])

    # --- RBAC: two new permissions, global catalog rows only -------------------
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

    op.drop_index("ix_provider_credentials_organization_id", table_name="provider_credentials")
    op.drop_table("provider_credentials")
