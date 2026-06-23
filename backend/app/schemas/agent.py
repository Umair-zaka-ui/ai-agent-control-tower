"""Agent schemas. ``api_key_hash`` is never exposed; the plaintext API key is
returned exactly once at creation time."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import AgentStatus


class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    agent_type: str = Field(..., min_length=1, max_length=100)


class AgentStatusUpdate(BaseModel):
    status: AgentStatus


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None
    agent_type: str
    status: AgentStatus
    created_at: datetime
    updated_at: datetime


class AgentCreateResponse(AgentRead):
    """Returned only on creation - includes the one-time plaintext API key."""

    api_key: str
