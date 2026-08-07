"""Phase 2.3.1 - External Identity Federation.

Two new, additive tables. No existing table is retyped, dropped, or has a
column removed.

- ``identity_federation_configs`` — one row per organization's IdP
  connection (OIDC or SAML). ``configuration`` is non-secret (endpoints,
  issuer, JWKS URI, the IdP's own *public* certificate); an OIDC client's
  own secret, if configured, is encrypted (``encrypted_client_secret``) via
  the platform's existing Fernet key, the same one every other stored
  platform secret in this codebase already uses.
- ``federated_identities`` — links one IdP subject (OIDC ``sub`` / SAML
  NameID) to an *existing* ``users.id`` row. No credential column of any
  kind — the platform never stores a federated user's own credential
  (``ACT-INT-FR-186``).

Revision ID: 0036_identity_federation
Revises: 0035_connector_health
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0036_identity_federation"
down_revision: str | None = "0035_connector_health"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_federation_configs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("protocol", sa.String(length=16), nullable=False),
        sa.Column("provider_type", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("configuration", JSONB(), nullable=False),
        sa.Column("encrypted_client_secret", sa.Text(), nullable=True),
        sa.Column("jit_provisioning_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("claim_mappings", JSONB(), nullable=False, server_default="{}"),
        sa.Column("default_role_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ACTIVE"),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["default_role_id"], ["roles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_identity_federation_configs_organization_id",
        "identity_federation_configs", ["organization_id"],
    )
    op.create_unique_constraint(
        "uq_identity_federation_configs_org_protocol_provider",
        "identity_federation_configs", ["organization_id", "protocol", "provider_type"],
    )

    op.create_table(
        "federated_identities",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("federation_config_id", sa.UUID(), nullable=False),
        sa.Column("external_subject_id", sa.String(length=255), nullable=False),
        sa.Column("last_federated_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["federation_config_id"], ["identity_federation_configs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_federated_identities_user_id", "federated_identities", ["user_id"])
    op.create_index("ix_federated_identities_organization_id", "federated_identities", ["organization_id"])
    op.create_index("ix_federated_identities_federation_config_id", "federated_identities", ["federation_config_id"])
    op.create_unique_constraint(
        "uq_federated_identities_config_subject",
        "federated_identities", ["federation_config_id", "external_subject_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_federated_identities_config_subject", "federated_identities", type_="unique")
    op.drop_index("ix_federated_identities_federation_config_id", "federated_identities")
    op.drop_index("ix_federated_identities_organization_id", "federated_identities")
    op.drop_index("ix_federated_identities_user_id", "federated_identities")
    op.drop_table("federated_identities")

    op.drop_constraint(
        "uq_identity_federation_configs_org_protocol_provider", "identity_federation_configs", type_="unique",
    )
    op.drop_index("ix_identity_federation_configs_organization_id", "identity_federation_configs")
    op.drop_table("identity_federation_configs")
