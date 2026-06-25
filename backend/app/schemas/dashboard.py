"""Dashboard schemas - aggregated metrics for the future frontend."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.core.enums import ActionDecision, ActionStatus, ApprovalPriority


class DashboardSummary(BaseModel):
    agents: int
    active_agents: int
    pending_approvals: int
    blocked_actions: int
    policies: int
    total_actions: int
    today_actions: int


class ActivityPoint(BaseModel):
    """A single day in the agent-activity series (last 7 days)."""

    date: str
    actions: int


class RiskTrendPoint(BaseModel):
    """A single day in the organizational risk series (last 30 days)."""

    date: str
    risk_score: int


class SystemHealth(BaseModel):
    """Per-service health: each value is 'healthy', 'warning' or 'offline'."""

    api: str
    database: str
    policy_engine: str
    approval_engine: str
    audit: str


class RecentActionItem(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    resource: str
    action: str
    risk_score: int
    decision: ActionDecision
    status: ActionStatus
    created_at: datetime


class PendingApprovalItem(BaseModel):
    id: uuid.UUID
    agent_action_id: uuid.UUID
    requested_by_agent_id: uuid.UUID
    priority: ApprovalPriority
    sla_due_at: datetime | None
    created_at: datetime
