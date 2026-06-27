"""Policy schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ActionDecision, PolicySeverity, PolicyStatus


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
    severity: PolicySeverity = PolicySeverity.MEDIUM
    status: PolicyStatus = PolicyStatus.ENABLED


class PolicyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    resource: str | None = None
    action: str | None = None
    conditions: dict[str, Any] | None = None
    decision: ActionDecision | None = None
    priority: int | None = None
    severity: PolicySeverity | None = None
    status: PolicyStatus | None = None


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
    severity: PolicySeverity
    status: PolicyStatus
    trigger_count: int
    last_triggered_at: datetime | None
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class PolicyTestRequest(BaseModel):
    agent_id: uuid.UUID | None = None
    resource: str = Field(..., min_length=1, max_length=100)
    action: str = Field(..., min_length=1, max_length=100)
    input_payload: dict[str, Any] = Field(default_factory=dict)


class PolicyTestResult(BaseModel):
    matched: bool
    decision: str | None
    reason: str
    risk_score: int
    triggered_conditions: list[str]
    explanation: str


class PolicyTemplate(BaseModel):
    key: str
    name: str
    description: str
    resource: str
    action: str
    conditions: dict[str, Any]
    decision: ActionDecision
    severity: PolicySeverity
