"""Request/response schemas for the SLO and alert API (Phase 4.7 §6)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# SLO definitions
# --------------------------------------------------------------------------- #
class SLOCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    sli: str
    target: float
    scope_type: str = "ORGANIZATION"
    scope_id: uuid.UUID | None = None
    window: str = "24h"
    error_budget: float | None = None
    enabled: bool = True


class SLOUpdate(BaseModel):
    name: str | None = None
    sli: str | None = None
    target: float | None = None
    scope_type: str | None = None
    scope_id: uuid.UUID | None = None
    window: str | None = None
    error_budget: float | None = None
    enabled: bool | None = None


class SLORead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    sli: str
    scope_type: str
    scope_id: uuid.UUID | None
    target: float
    window: str
    error_budget: float
    enabled: bool
    created_at: datetime
    updated_at: datetime


class SLOEvaluationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slo_id: uuid.UUID
    window_start: datetime
    window_end: datetime
    sample_count: int
    observed_value: float | None
    state: str
    budget_consumed: float | None
    budget_remaining: float | None
    explanation: dict
    evaluated_at: datetime


# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #
class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    source: str
    source_id: uuid.UUID | None
    slo_id: uuid.UUID | None
    severity: str
    status: str
    agent_id: uuid.UUID | None
    agent_version_id: uuid.UUID | None
    environment_id: uuid.UUID | None
    execution_id: uuid.UUID | None
    trace_id: str | None
    metric: str
    threshold_value: float | None
    observed_value: float | None
    baseline_value: float | None
    title: str
    summary: str
    dedup_key: str
    context: dict
    recurrence_count: int
    opened_at: datetime
    last_seen_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by: uuid.UUID | None
    resolved_at: datetime | None
    resolved_by: uuid.UUID | None
    suppressed_at: datetime | None
    updated_at: datetime


class AlertTransitionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)
