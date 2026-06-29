"""Approval schemas.

Phase 3 Part 3.4 expands these to power the Human Review Workbench: enriched
list items, a full detail payload (agent / policy / risk / payload / comments),
queue statistics and the escalate / assign request bodies.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ApprovalDecision, ApprovalPriority, EscalationTarget


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #
class ApprovalReviewRequest(BaseModel):
    """Optional reviewer comment supplied when approving/rejecting."""

    review_comment: str | None = Field(default=None, max_length=2000)


class ApprovalEscalateRequest(BaseModel):
    """Escalate an approval to a person or team, with a mandatory reason."""

    target: EscalationTarget
    reason: str = Field(..., min_length=1, max_length=2000)
    assigned_to_user_id: uuid.UUID | None = None


class ApprovalAssignRequest(BaseModel):
    """Assign (or reassign) the reviewer responsible for an approval."""

    user_id: uuid.UUID


class ApprovalCommentCreate(BaseModel):
    comment: str = Field(..., min_length=1, max_length=2000)


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
class ApprovalCommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    approval_id: uuid.UUID
    user_id: uuid.UUID | None
    comment: str
    created_at: datetime


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    agent_action_id: uuid.UUID
    requested_by_agent_id: uuid.UUID
    reviewed_by_user_id: uuid.UUID | None
    assigned_to_user_id: uuid.UUID | None
    decision: ApprovalDecision
    priority: ApprovalPriority
    review_comment: str | None
    escalation_target: str | None
    sla_due_at: datetime | None
    escalated_at: datetime | None
    created_at: datetime
    reviewed_at: datetime | None


class ApprovalListItem(BaseModel):
    """A row in the approval queue / history table (joined with agent + action)."""

    id: uuid.UUID
    agent_action_id: uuid.UUID
    requested_by_agent_id: uuid.UUID
    agent_name: str | None
    resource: str
    action: str
    risk_score: int
    decision: ApprovalDecision
    priority: ApprovalPriority
    escalation_target: str | None
    reviewer_name: str | None
    assigned_to_name: str | None
    sla_due_at: datetime | None
    created_at: datetime
    reviewed_at: datetime | None


# --- Nested detail blocks --------------------------------------------------- #
class ApprovalAgentInfo(BaseModel):
    id: uuid.UUID
    name: str
    version: str | None = None
    owner: str | None = None
    department: str | None = None
    status: str | None = None
    health: str | None = None
    last_activity: datetime | None = None


class ApprovalActionInfo(BaseModel):
    id: uuid.UUID
    resource: str
    action: str
    input_payload: dict[str, Any]
    risk_score: int
    decision: str
    decision_reason: str
    status: str
    created_at: datetime


class ApprovalPolicyInfo(BaseModel):
    matched: bool
    policy_name: str | None = None
    decision: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None


class ApprovalRiskAssessment(BaseModel):
    score: int
    action_score: int
    resource_score: int
    factors: dict[str, int] = Field(default_factory=dict)
    confidence: int
    recommendation: str


class ApprovalDetail(ApprovalRead):
    """Everything the review workbench needs for a single approval."""

    reviewer_name: str | None = None
    assigned_to_name: str | None = None
    agent: ApprovalAgentInfo | None = None
    action: ApprovalActionInfo | None = None
    policy: ApprovalPolicyInfo
    risk: ApprovalRiskAssessment
    comments: list[ApprovalCommentRead] = Field(default_factory=list)


class ApprovalTimelineEvent(BaseModel):
    """A single audit-derived event on an approval's review timeline."""

    id: uuid.UUID
    event_type: str
    actor_type: str
    actor_id: uuid.UUID | None = None
    actor_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ApprovalStatistics(BaseModel):
    pending: int
    approved_today: int
    rejected_today: int
    escalated: int
    avg_review_seconds: int | None = None
