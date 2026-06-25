"""Agent schemas. ``api_key_hash`` is never exposed; the plaintext API key is
returned exactly once at creation time."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import AgentHealth, AgentStatus, RiskLevel


class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    agent_type: str = Field(..., min_length=1, max_length=100)
    owner: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    version: str = Field(default="1.0.0", max_length=50)
    capabilities: list[str] = Field(default_factory=list)
    default_risk_score: int = Field(default=0, ge=0, le=100)
    max_allowed_risk: int = Field(default=100, ge=0, le=100)
    human_approval_required: bool = False
    auto_suspend_threshold: int | None = Field(default=None, ge=0, le=100)
    risk_level: RiskLevel = RiskLevel.LOW


class AgentUpdate(BaseModel):
    """All fields optional - only provided keys are updated."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    agent_type: str | None = Field(default=None, min_length=1, max_length=100)
    owner: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    version: str | None = Field(default=None, max_length=50)
    capabilities: list[str] | None = None
    default_risk_score: int | None = Field(default=None, ge=0, le=100)
    max_allowed_risk: int | None = Field(default=None, ge=0, le=100)
    human_approval_required: bool | None = None
    auto_suspend_threshold: int | None = Field(default=None, ge=0, le=100)
    risk_level: RiskLevel | None = None
    status: AgentStatus | None = None


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
    owner: str | None
    department: str | None
    version: str
    capabilities: list[str]
    default_risk_score: int
    max_allowed_risk: int
    human_approval_required: bool
    auto_suspend_threshold: int | None
    risk_level: RiskLevel
    health: AgentHealth
    created_at: datetime
    updated_at: datetime


class AgentCreateResponse(AgentRead):
    """Returned only on creation - includes the one-time plaintext API key."""

    api_key: str


class AgentListResponse(BaseModel):
    """Paginated list envelope for the agents table."""

    items: list[AgentRead]
    total: int
    page: int
    page_size: int


class AgentStats(BaseModel):
    """Per-agent operational statistics for the details Overview."""

    actions_today: int
    total_actions: int
    blocked_actions: int
    pending_approvals: int
    policies_triggered: int
    average_risk: int
    success_rate: float
