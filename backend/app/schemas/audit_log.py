"""Audit log schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ActorType


class AuditLogRead(BaseModel):
    # ``populate_by_name`` lets us read the ORM attribute ``meta`` while still
    # exposing the field publicly as ``metadata``.
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    actor_type: ActorType
    actor_id: uuid.UUID | None
    event_type: str
    entity_type: str
    entity_id: uuid.UUID | None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="meta")
    created_at: datetime
