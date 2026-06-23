"""Agent action schemas - the heart of the governance workflow."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ActionDecision, ActionStatus


class AgentActionCreate(BaseModel):
    agent_id: uuid.UUID
    resource: str = Field(..., min_length=1, max_length=100)
    action: str = Field(..., min_length=1, max_length=100)
    input_payload: dict[str, Any] = Field(default_factory=dict)


class AgentActionDecisionResponse(BaseModel):
    """Compact response returned by ``POST /agent-actions`` (matches the spec)."""

    agent_action_id: uuid.UUID
    decision: ActionDecision
    risk_score: int
    decision_reason: str
    status: ActionStatus
    approval_id: uuid.UUID | None = None


class AgentActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    agent_id: uuid.UUID
    resource: str
    action: str
    input_payload: dict[str, Any]
    output_payload: dict[str, Any] | None
    risk_score: int
    decision: ActionDecision
    decision_reason: str
    status: ActionStatus
    created_at: datetime
    updated_at: datetime
