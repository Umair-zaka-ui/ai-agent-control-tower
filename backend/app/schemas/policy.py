"""Policy schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ActionDecision


class PolicyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    resource: str = Field(..., min_length=1, max_length=100)
    action: str = Field(..., min_length=1, max_length=100)
    conditions: dict[str, Any] = Field(
        default_factory=dict,
        description='Condition map, e.g. {"amount_gt": 10000}. Empty = always matches.',
    )
    decision: ActionDecision
    priority: int = 0
    enabled: bool = True


class PolicyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    conditions: dict[str, Any] | None = None
    decision: ActionDecision | None = None
    priority: int | None = None
    enabled: bool | None = None


class PolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None
    resource: str
    action: str
    conditions: dict[str, Any]
    decision: str
    priority: int
    enabled: bool
    created_at: datetime
    updated_at: datetime
