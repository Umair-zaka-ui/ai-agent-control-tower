"""ABAC API schemas (Phase 4.3.5 §15, §30, §31)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# --- Policies (§6) ----------------------------------------------------------- #
class PolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    policy_family_id: uuid.UUID
    organization_id: uuid.UUID | None = None
    name: str
    description: str | None = None
    version: int
    status: str
    priority: int
    combining_algorithm: str
    scope_type: str
    scope_id: uuid.UUID | None = None
    target: dict | None = None
    conditions: dict | None = None
    effect: str
    obligations: dict | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    created_by: uuid.UUID | None = None
    updated_by: uuid.UUID | None = None
    published_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PolicyWrite(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    priority: int | None = Field(default=None, ge=0, le=10000)
    combining_algorithm: str | None = None
    scope_type: str | None = None
    scope_id: uuid.UUID | None = None
    target: dict | None = None
    conditions: dict | None = None
    effect: str | None = None
    obligations: dict | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class ValidationResult(BaseModel):
    policy_id: uuid.UUID
    valid: bool
    status: str
    errors: list[dict] = []


class PolicyVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    policy_family_id: uuid.UUID
    version: int
    snapshot: dict
    created_by: uuid.UUID | None = None
    created_at: datetime | None = None


# --- Attributes (§20) ----------------------------------------------------------- #
class AttributeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    category: str
    data_type: str
    description: str | None = None
    sensitivity: str
    supported_operators: list | None = None
    source: str | None = None
    is_system: bool
    enabled: bool


class AttributeCreate(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    category: str
    data_type: str
    description: str | None = None
    sensitivity: str = "INTERNAL"
    supported_operators: list[str] | None = None


class AttributeUpdate(BaseModel):
    description: str | None = None
    sensitivity: str | None = None
    supported_operators: list[str] | None = None
    enabled: bool | None = None


# --- Decisions (§15, §31) --------------------------------------------------------- #
class ABACDecisionRead(BaseModel):
    decision: str
    allowed: bool
    reason: str
    matched_policies: list[dict] = []
    obligations: list[dict] = []
    explanation: dict = {}
    evaluation_time_ms: float = 0.0
    request_id: str | None = None
    applicable: bool = True


class EvaluateRequest(BaseModel):
    action: str = Field(min_length=1, max_length=100)
    resource_pk: uuid.UUID | None = None
    context: dict[str, Any] | None = None


class SimulateRequest(BaseModel):
    action: str = Field(min_length=1, max_length=100)
    identity_id: uuid.UUID | None = None
    resource_pk: uuid.UUID | None = None
    context: dict[str, Any] | None = None
    # For POST /policies/{id}/simulate the stored policy is used; the generic
    # /simulate endpoint may carry an inline draft policy instead.
    policy: dict | None = None


class SimulationRead(BaseModel):
    baseline_rbac: dict
    resource_authorization: dict | None = None
    abac: ABACDecisionRead


# --- Evaluations (§36) ----------------------------------------------------------- #
class EvaluationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    identity_id: uuid.UUID | None = None
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None
    action: str
    decision: str
    matched_policy_ids: list | None = None
    obligations: list | None = None
    explanation: dict | None = None
    evaluation_time_ms: float | None = None
    request_id: str | None = None
    correlation_id: str | None = None
    created_at: datetime | None = None


# --- Exceptions (§21) --------------------------------------------------------------- #
class ExceptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    policy_id: uuid.UUID
    subject_type: str
    subject_id: uuid.UUID
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None
    reason: str | None = None
    approved_by: uuid.UUID | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    status: str
    created_at: datetime | None = None


class ExceptionCreate(BaseModel):
    policy_id: uuid.UUID
    subject_type: str = "USER"
    subject_id: uuid.UUID
    resource_type: str | None = None
    resource_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=500)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
