"""Phase 4.8 -- request/response models for the telemetry-privacy API."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.telemetry_privacy.modes import CAPTURE_MODES
from app.telemetry_privacy.retention import TELEMETRY_CLASSES


class CapturePolicyCreate(BaseModel):
    mode: str = Field(description=f"One of {list(CAPTURE_MODES)}")
    environment_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    classification: str | None = None
    enabled: bool = True


class CapturePolicyUpdate(BaseModel):
    mode: str | None = None
    environment_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    classification: str | None = None
    enabled: bool | None = None


class CapturePolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None
    environment_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    classification: str | None
    mode: str
    enabled: bool
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class RetentionPolicyWrite(BaseModel):
    telemetry_class: str = Field(description=f"One of {list(TELEMETRY_CLASSES)}")
    retention_days: int = Field(gt=0)
    enabled: bool = True


class EffectiveModeQuery(BaseModel):
    environment_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    classification: str | None = None
