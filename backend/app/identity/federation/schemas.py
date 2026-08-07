"""Request/response DTOs for federation endpoints (Phase 2.3.1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FederationConfigCreate(BaseModel):
    protocol: str = Field(..., pattern="^(OIDC|SAML)$")
    provider_type: str = Field(..., pattern="^(ENTRA_ID|OKTA|GENERIC_OIDC|GENERIC_SAML)$")
    display_name: str = Field(..., min_length=1, max_length=128)
    configuration: dict[str, Any]
    # The SP's OWN OIDC client secret -- never the user's credential. Optional:
    # a public OIDC client, or SAML entirely, needs none.
    client_secret: str | None = None
    jit_provisioning_enabled: bool = False
    claim_mappings: dict[str, Any] | None = None
    default_role_id: uuid.UUID | None = None


class FederationConfigUpdate(BaseModel):
    display_name: str | None = None
    configuration: dict[str, Any] | None = None
    client_secret: str | None = None
    jit_provisioning_enabled: bool | None = None
    claim_mappings: dict[str, Any] | None = None
    default_role_id: uuid.UUID | None = None
    status: str | None = Field(default=None, pattern="^(ACTIVE|DISABLED)$")


class FederationConfigRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    protocol: str
    provider_type: str
    display_name: str
    configuration: dict[str, Any]
    jit_provisioning_enabled: bool
    claim_mappings: dict[str, Any]
    default_role_id: uuid.UUID | None
    status: str
    created_at: datetime
    updated_at: datetime
    # Never the secret itself, encrypted or otherwise -- only whether one is
    # configured, the same "hint, never ciphertext" discipline 2.1.2's own
    # ConnectorCredentialRead established.
    has_client_secret: bool


class FederationConfigTestResult(BaseModel):
    success: bool
    message: str


class OidcCallbackRequest(BaseModel):
    code: str
    state: str
