"""Approval schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ApprovalDecision


class ApprovalReviewRequest(BaseModel):
    """Optional reviewer comment supplied when approving/rejecting."""

    review_comment: str | None = Field(default=None, max_length=2000)


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    agent_action_id: uuid.UUID
    requested_by_agent_id: uuid.UUID
    reviewed_by_user_id: uuid.UUID | None
    decision: ApprovalDecision
    review_comment: str | None
    created_at: datetime
    reviewed_at: datetime | None
