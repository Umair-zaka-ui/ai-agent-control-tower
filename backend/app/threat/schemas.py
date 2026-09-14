"""Pydantic schemas for the Phase 5.6 (M5.6) threat + containment API.

Findings are never client-submitted (they are derived deterministically from
runtime signals — §9 threat model, "finding poisoning"); the only writes are
finding-lifecycle transitions and containment-execute requests.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ThreatFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    rule_id: str
    rule_version: str
    ruleset_version: str
    outcome: str
    severity: str
    status: str
    agent_id: uuid.UUID
    reason: str
    attribution: dict
    evidence: dict
    recurrence_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    suppressed_at: datetime | None


class FindingTransition(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class ContainmentExecuteRequest(BaseModel):
    action_type: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=1, max_length=2000)
    target_id: uuid.UUID | None = None
    threat_finding_id: uuid.UUID | None = None
    #: Explicit confirmation for a dangerous action. Omitted/false queues the
    #: action as PENDING_CONFIRMATION without invoking any authority.
    confirm: bool = False


class ContainmentActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    action_type: str
    authority: str
    trigger: str
    threat_finding_id: uuid.UUID | None
    triggered_by_user_id: uuid.UUID | None
    automated: bool
    agent_id: uuid.UUID
    target_type: str | None
    target_id: uuid.UUID | None
    control_state_at_time: str
    status: str
    requires_confirmation: bool
    confirmed_by: uuid.UUID | None
    confirmed_at: datetime | None
    reason: str
    refusal_reason: str | None
    authority_ref: dict | None
    result: dict
    reversible: bool
    reverted_at: datetime | None
    created_at: datetime


__all__ = [
    "ThreatFindingRead",
    "FindingTransition",
    "ContainmentExecuteRequest",
    "ContainmentActionRead",
]
