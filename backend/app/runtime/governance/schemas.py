"""Request/response schemas for the runtime governance API (§6)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GovernancePolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    environment_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    # Validated in the service against the known constraint set rather than
    # typed field-by-field here: the document is intentionally open-ended (a
    # new governed limit should not need a migration *or* a schema change),
    # and a permissive schema plus a strict validator keeps the rejection
    # message specific -- "Unknown constraint 'max_execution_costs'" rather
    # than a generic shape error.
    constraints: dict = Field(default_factory=dict)
    mandatory: bool = False
    enabled: bool = True


class GovernancePolicyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    environment_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    constraints: dict | None = None
    mandatory: bool | None = None
    enabled: bool | None = None


class GovernancePolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None
    environment_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    name: str
    description: str | None
    constraints: dict
    mandatory: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None


class GovernanceDecisionRead(BaseModel):
    """One row of the "why did this execution stop" lineage.

    Metadata only, and deliberately so: ``reason`` is a message this codebase
    templates from its own constraint definitions (a ceiling, a tool name, a
    model name), never a prompt, a tool argument or model output. The Phase 4.2
    content boundary is not weakened by this surface.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    execution_id: uuid.UUID
    trace_id: str | None
    checkpoint: str
    decision: str
    reason_code: str
    reason: str | None
    obligation: dict | None
    policy_id: uuid.UUID | None
    iteration: int | None
    evaluated_at: datetime
