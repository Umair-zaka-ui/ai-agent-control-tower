"""Agent API key schemas. The raw key is returned only once at creation."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import ApiKeyStatus


class ApiKeyCreate(BaseModel):
    # Optional expiry; omit for a non-expiring key.
    expires_at: datetime | None = None


class ApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    key_prefix: str
    status: ApiKeyStatus
    last_used_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


class ApiKeyCreateResponse(BaseModel):
    """Includes the one-time plaintext key. Store it now - it is never shown again."""

    id: uuid.UUID
    agent_id: uuid.UUID
    key_prefix: str
    api_key: str
