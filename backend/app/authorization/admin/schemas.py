"""Pydantic schemas for the administration portal API (Phase 4.3.7 §18)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Dashboard (§6)
# --------------------------------------------------------------------------- #
class DashboardWidgets(BaseModel):
    total_users: int
    active_roles: int
    active_permissions: int
    active_policies: int
    active_sessions: int
    authorization_requests_24h: int
    denied_requests_24h: int
    approval_requests_pending: int
    mfa_challenges_total: int
    high_risk_decisions_24h: int
    cache_hit_ratio: float
    policy_evaluation_latency_ms: float


class DashboardCharts(BaseModel):
    authorization_trend: list[dict]        # [{date, total, denied}]
    top_permissions: list[dict]            # [{permission, total, denied}]
    policy_matches: list[dict]             # [{policy, matches}]
    decision_breakdown: list[dict]         # [{decision, total}]
    approval_queue: list[dict]             # [{status, total}]


class DashboardRead(BaseModel):
    widgets: DashboardWidgets
    charts: DashboardCharts


# --------------------------------------------------------------------------- #
# Decision explorer (§13)
# --------------------------------------------------------------------------- #
class DecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    identity_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    permission: str
    resource_type: str | None
    resource_id: uuid.UUID | None
    allowed: bool
    reason: str | None
    scope: str | None
    source_role: str | None
    evaluation_time_ms: float | None
    request_id: str | None
    created_at: datetime


# --------------------------------------------------------------------------- #
# Access reviews (§14)
# --------------------------------------------------------------------------- #
class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    # {"role_ids": [...], "include_system_roles": bool} — empty = all assignments.
    scope: dict | None = None
    reviewer_id: uuid.UUID | None = None
    due_at: datetime | None = None


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    scope: dict | None = None
    reviewer_id: uuid.UUID | None = None
    due_at: datetime | None = None


class ReviewItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    subject_id: uuid.UUID
    subject_label: str
    assignment_id: uuid.UUID | None
    role_id: uuid.UUID | None
    role_name: str
    scope_label: str | None
    decision: str
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    comment: str | None


class CampaignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None
    status: str
    scope: dict | None
    reviewer_id: uuid.UUID | None
    due_at: datetime | None
    created_by: uuid.UUID | None
    activated_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    total_items: int = 0
    decided_items: int = 0
    revoked_items: int = 0


class ItemDecision(BaseModel):
    decision: str = Field(pattern="^(CERTIFIED|REVOKED)$")
    comment: str | None = Field(default=None, max_length=500)


# --------------------------------------------------------------------------- #
# Security analytics (§17)
# --------------------------------------------------------------------------- #
class AnalyticsRead(BaseModel):
    denied_requests_24h: int
    denied_requests_7d: int
    high_risk_decisions_24h: int
    mfa_challenges_total: int
    approval_requests_total: int
    approval_approval_rate: float
    authorization_latency_ms_avg: float
    authorization_latency_ms_p95: float
    cache_hit_ratio: float
    abac_denies_total: int
    abac_challenges_total: int
    policy_errors_total: int
    top_denied_permissions: list[dict]     # [{permission, denied}]
    denied_trend: list[dict]               # [{date, denied}]
    sharing_trend: list[dict]              # [{date, shares}]
