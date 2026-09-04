"""Pydantic schemas for the Phase 5.2 (M5.2) Agent Discovery Framework API."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class DiscoverySourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    adapter_key: str = Field(min_length=1, max_length=64)
    config: dict = Field(default_factory=dict)
    secret: str | None = None
    enabled: bool = True
    missed_sweeps_before_stale: int = Field(default=1, ge=1)


class DiscoverySourceUpdate(BaseModel):
    config: dict | None = None
    secret: str | None = None
    enabled: bool | None = None
    missed_sweeps_before_stale: int | None = Field(default=None, ge=1)


class DiscoverySourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    adapter_key: str
    config: dict
    secret_hint: str | None
    enabled: bool
    missed_sweeps_before_stale: int
    last_run_at: datetime | None
    last_run_status: str | None
    created_at: datetime
    updated_at: datetime


class DiscoveryRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    source_id: uuid.UUID
    status: str
    trigger: str
    started_at: datetime | None
    ended_at: datetime | None
    checkpoint: dict
    observations_count: int
    agents_created: int
    agents_linked: int
    findings_created: int
    error: str | None
    created_at: datetime


class DiscoveryRunTriggerRequest(BaseModel):
    pass


class DiscoveryFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    finding_type: str
    source_id: uuid.UUID | None
    run_id: uuid.UUID | None
    observation_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    external_identifier: str | None
    confidence: Decimal | None
    reason: str
    status: str
    resolved_by: uuid.UUID | None
    resolved_at: datetime | None
    created_at: datetime


class DiscoveryFindingResolveRequest(BaseModel):
    status: str = Field(pattern="^(RESOLVED|DISMISSED)$")


class DiscoveryAdapterRead(BaseModel):
    adapter_key: str
    display_name: str
    config_schema: dict
    requires_secret: bool
