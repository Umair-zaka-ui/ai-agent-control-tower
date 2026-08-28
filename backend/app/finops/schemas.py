"""Request/response schemas for the cost and budget API (§6)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CostBucketRead(BaseModel):
    key: str
    label: str | None
    actual_amount: float
    estimated_amount: float
    execution_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    currency: str


class CostSummaryRead(BaseModel):
    """Actual and estimated are two fields, never one total.

    ``cost_is_estimated`` exists on the execution row because the platform
    sometimes cannot meter a call. Adding those into a single number labelled
    "spend" would produce a figure an operator takes to their finance team, so
    the split is carried all the way out to the wire. ``unpriced_execution_count``
    is the third honest number: executions the platform could not price at all,
    which count in neither sum and would otherwise silently read as zero."""

    window_start: datetime
    window_end: datetime
    actual_amount: float
    estimated_amount: float
    execution_count: int
    total_tokens: int
    unpriced_execution_count: int
    currency: str
    dimension: str | None
    buckets: list[CostBucketRead]


class SpendAnomalyRead(BaseModel):
    period: str
    amount: float
    baseline: float
    ratio: float
    threshold_ratio: float
    reason: str


class BudgetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    scope_type: str
    scope_id: uuid.UUID | None = None
    scope_value: str | None = Field(default=None, max_length=128)
    mode: str = "INFORMATIONAL"
    period: str = "MONTHLY"
    limit_amount: float = Field(ge=0)
    currency: str = Field(default="USD", max_length=8)
    reservation_estimate: float | None = Field(default=None, ge=0)
    threshold_percent: int = Field(default=80, ge=1, le=100)
    enabled: bool = True


class BudgetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    scope_type: str | None = None
    scope_id: uuid.UUID | None = None
    scope_value: str | None = Field(default=None, max_length=128)
    mode: str | None = None
    period: str | None = None
    limit_amount: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)
    reservation_estimate: float | None = Field(default=None, ge=0)
    threshold_percent: int | None = Field(default=None, ge=1, le=100)
    enabled: bool | None = None


class BudgetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None
    scope_type: str
    scope_id: uuid.UUID | None
    scope_value: str | None
    mode: str
    period: str
    limit_amount: float
    currency: str
    reservation_estimate: float | None
    threshold_percent: int
    enabled: bool
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None


class BudgetUtilizationRead(BaseModel):
    budget_id: uuid.UUID
    mode: str
    period: str
    period_key: str
    limit_amount: float
    reserved: float
    spent: float
    committed: float
    remaining: float
    utilization_percent: float
    threshold_percent: int
    over_threshold: bool
    currency: str


class CostProvenanceRead(BaseModel):
    """§10 — how one charge was arrived at, reconstructable after the fact.

    Every field was written at execution time and is never updated.
    ``PricingService.set_price`` closes the old price row and inserts a new one
    rather than mutating in place, so ``pricing_version`` still names the exact
    price document that produced ``calculated_amount``."""

    execution_id: str
    provider: str | None
    model: str | None
    pricing_version: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    token_accounting_complete: bool
    calculated_amount: float | None
    currency: str
    is_estimated: bool
    calculated_at: datetime | None
