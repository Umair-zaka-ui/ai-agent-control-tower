"""Request/response schemas for the behavioral signals API (§6)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BehavioralFindingRead(BaseModel):
    """One finding, carrying its own explanation.

    ``explanation`` is deliberately part of the read model rather than an
    internal detail: a consumer that received a state without the numbers
    behind it would be back to an unauditable score, which is the thing this
    phase exists not to build."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    agent_id: uuid.UUID
    agent_version_id: uuid.UUID | None
    environment_id: uuid.UUID | None
    signal_type: str
    state: str
    metric: str
    window_start: datetime
    window_end: datetime
    sample_count: int
    observed_value: float | None
    threshold_value: float | None
    baseline_value: float | None
    attribution: dict[str, Any]
    explanation: dict[str, Any]
    evaluated_at: datetime


class SignalRead(BaseModel):
    signal_type: str
    metric: str
    state: str
    reason: str
    observed_value: float | None
    threshold_value: float | None
    baseline_value: float | None
    attribution: dict[str, Any]


class BehavioralEvaluationRead(BaseModel):
    """The result of one evaluation.

    Every signal is returned, including the ``NORMAL`` ones that produce no
    persisted finding — the caller asked for an evaluation and "we looked at
    latency and it was fine" is part of the answer. ``findings_recorded`` says
    how many of them were durable."""

    agent_id: uuid.UUID
    window_start: datetime
    window_end: datetime
    sample_count: int
    baseline_sample_count: int
    signals: list[SignalRead]
    findings_recorded: int


class EvaluateRequest(BaseModel):
    agent_id: uuid.UUID
    # Bounded at the schema and again in the service, so an internal caller
    # cannot bypass it -- the same two-sided clamp Phase 4.2's explorer uses
    # for its page size.
    window_days: int | None = Field(default=None, ge=1, le=90)
