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
