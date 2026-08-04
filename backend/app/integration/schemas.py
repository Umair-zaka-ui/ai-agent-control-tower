"""Phase 2.1.1 — Pydantic request/response schemas for ``/api/v1/integration``."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConnectorTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    connector_type: str
    version: str
    capabilities: dict[str, Any]
    config_schema: dict[str, Any]
    auth_requirements: dict[str, Any]
    tool_contracts: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class ConnectorInstanceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    connector_id: uuid.UUID
    name: str
    configuration: dict[str, Any]
    lifecycle_state: str
    state_reason: str | None
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None


class ConnectorLifecycleEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    connector_instance_id: uuid.UUID
    from_state: str | None
    to_state: str
    reason: str | None
    actor_id: uuid.UUID | None
    created_at: datetime


class ConnectorInstanceCreate(BaseModel):
    connector_type: str = Field(min_length=1, max_length=64)
    version: str | None = Field(default=None, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    configuration: dict[str, Any] | None = None


class ConnectorInstanceConfigure(BaseModel):
    configuration: dict[str, Any]


class ConnectorDisableRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


# --------------------------------------------------------------------------- #
# Phase 2.1.2 — Connector Authentication Framework
# --------------------------------------------------------------------------- #
class ConnectorCredentialRead(BaseModel):
    """Metadata and a masked hint only — **never** the credential value
    (``ACT-INT-FR-025``)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    connector_instance_id: uuid.UUID
    auth_scheme: str
    secret_hint: str
    status: str
    last_validated_at: datetime | None
    validation_status: str | None
    created_at: datetime
    updated_at: datetime


class ConnectorCredentialUpsert(BaseModel):
    auth_scheme: str = Field(min_length=1, max_length=48)
    credential: dict[str, Any] = Field(min_length=1)


class ConnectorCredentialValidationResult(BaseModel):
    success: bool
    validation_status: str
    message: str


class AuthSchemeRead(BaseModel):
    identifier: str
    required_fields: list[str]


class OAuthCallbackRequest(BaseModel):
    """Body for ``POST .../oauth/callback`` — the manual/API-driven
    exchange entry point (the ``GET`` variant takes the same value as a
    query parameter, matching a real OAuth2 redirect)."""

    code: str = Field(min_length=1)
    state: str | None = None


class OAuthAuthorizationUrlRead(BaseModel):
    authorization_url: str


class OAuthCallbackResult(BaseModel):
    """Never the token value — confirmation only (``ACT-INT-FR-025``)."""

    status: str
    connector_instance_id: uuid.UUID
    auth_scheme: str
