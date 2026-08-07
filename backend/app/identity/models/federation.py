"""External identity federation models (Phase 2.3.1, ACT-INT-FR-180..187).

**The inversion, stated once here since it shapes both tables.** A connector
(Phase 2.1.2) holds a *platform* secret and presents it outward. Federation
holds no *user* secret at all — it verifies a signed assertion from the
enterprise's own IdP and trusts it. Two tables, and what each deliberately
does and does not store:

- ``identity_federation_configs`` (``FederationConfig``) — one row per
  organization's IdP connection. ``configuration`` holds endpoints, the IdP's
  own *public* verification material (a SAML certificate, an OIDC JWKS/
  discovery URI) — public by definition, safe to read, but integrity-critical
  (tampering with it is an authentication bypass, so it is protected by the
  same RBAC as any other admin-only config, not by secrecy).
  ``encrypted_client_secret`` is nullable and holds the *platform's own*
  OIDC client secret (the SP authenticating itself to the IdP's token
  endpoint) — encrypted via the same ``credential_crypto.py`` Fernet key
  every other platform-held secret in this codebase already uses. This is
  the platform's credential. It is never the user's.
- ``federated_identities`` (``FederatedIdentity``) — links one IdP's stable
  subject identifier (OIDC ``sub`` / SAML ``NameID``) to an *existing*
  ``users.id`` row. This is the "maps into the existing model, never a
  parallel one" mechanism (``ACT-INT-FR-182``) — there is no name, no email,
  no role, and, critically, **no credential column** here: nothing about the
  user's actual authentication secret is stored anywhere, because the
  platform never receives it in the first place — only a claim, and after
  verification, nothing of the user's own beyond the fact that this subject
  id maps to this platform user.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class FederationConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One organization's IdP connection (table ``identity_federation_configs``,
    ``ACT-INT-FR-185`` — federation is per organization)."""

    __tablename__ = "identity_federation_configs"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    protocol: Mapped[str] = mapped_column(String(16), nullable=False)  # "OIDC" | "SAML"
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # "ENTRA_ID" | "OKTA" | "GENERIC_OIDC" | "GENERIC_SAML"
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # Non-secret / public: endpoints, issuer, audience, JWKS URI, SAML IdP
    # certificate (public verification key), claim-name overrides.
    configuration: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # The SP's OWN OIDC client secret, encrypted -- never the user's credential.
    # Nullable: a public OIDC client, or SAML entirely, needs none.
    encrypted_client_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    jit_provisioning_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    # IdP group/role claim -> platform role mapping rules (ACT-INT-FR-183).
    # {"group_claim": "groups", "rules": [{"idp_value": "...", "role_name": "..."}]}
    claim_mappings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Fallback role for a JIT-provisioned user whose claims matched no rule.
    # Nullable: a config with no default simply cannot JIT-provision an
    # unmapped user (rejected, not silently over-privileged).
    default_role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="SET NULL"), nullable=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )

    @property
    def is_active(self) -> bool:
        return self.status == "ACTIVE"


class FederatedIdentity(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Links one IdP subject to an existing platform user (table
    ``federated_identities``). **No credential column** — see module
    docstring."""

    __tablename__ = "federated_identities"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    federation_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("identity_federation_configs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # OIDC `sub` or SAML NameID -- a stable, IdP-issued identifier. Never
    # email: email can change and can be reassigned by an IdP administrator,
    # which would silently reattach one platform account to a different
    # human. The subject id is the link key precisely because it cannot.
    external_subject_id: Mapped[str] = mapped_column(String(255), nullable=False)
    last_federated_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
