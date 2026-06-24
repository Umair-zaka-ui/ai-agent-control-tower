"""Approval schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ApprovalDecision, ApprovalPriority


class ApprovalReviewRequest(BaseModel):
    """Optional reviewer comment supplied when approving/rejecting."""

    review_comment: str | None = Field(default=None, max_length=2000)


class ApprovalCommentCreate(BaseModel):
    comment: str = Field(..., min_length=1, max_length=2000)


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
    decision: ApprovalDecision
    priority: ApprovalPriority
    review_comment: str | None
    sla_due_at: datetime | None
    created_at: datetime
    reviewed_at: datetime | None
