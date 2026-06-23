"""Permission schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PermissionCreate(BaseModel):
    agent_id: uuid.UUID
    resource: str = Field(..., min_length=1, max_length=100)
    action: str = Field(..., min_length=1, max_length=100)
    allowed: bool = True


class PermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    agent_id: uuid.UUID
    resource: str
    action: str
    allowed: bool
    created_at: datetime
    updated_at: datetime
