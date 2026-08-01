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
