"""Phase 5.7 (M5.7) - request/response schemas for the external governance
bridge.

Two things are deliberate here. First, **no write schema carries
``control_state`` or an effective mode** -- the mode is derived and the
transition endpoint takes only a *requested* target, exactly the Phase 5.1
convention that keeps server-authoritative meaningful. Second, every
mode-bearing response carries ``limits`` beside ``display``: a client cannot
render ACT's claim without also receiving what ACT cannot do.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.bridge.modes import SETTABLE_MODES


class EnforcementModeRead(BaseModel):
    enforcement_mode: str
    control_state: str
    display: str
    limits: str
    reaches_boundary_calls: bool
    reaches_agent_execution: bool
    evaluates_policy: bool
    derived_from_control_state: bool


class EnforcementModeSet(BaseModel):
    target_mode: Literal["OBSERVED", "ADVISORY", "GATEWAY_ENFORCED"]
    reason: str | None = Field(default=None, max_length=1000)


class GrantScopeEntry(BaseModel):
    capability: str = Field(max_length=64)
    target_ref: str | None = Field(default=None, max_length=255)


class GrantCreate(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    scope: list[GrantScopeEntry] = Field(min_length=1, max_length=50)
    expires_at: datetime | None = None
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10_000)


class GrantRead(BaseModel):
    """Note the absence of any secret field. The plaintext is returned once,
    by ``GrantIssued`` below, and the ciphertext is never serialized at all."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    label: str
    key_id: str
    secret_hint: str
    scope: list[dict]
    expires_at: datetime | None
    revoked_at: datetime | None
    revocation_reason: str | None
    rate_limit_per_minute: int
    last_used_at: datetime | None
    created_at: datetime


class GrantIssued(BaseModel):
    """The only response in the platform that carries the signing secret. It
    is shown once and never retrievable again."""

    grant: GrantRead
    secret: str
    signature_scheme: str
    signing_instructions: str


class GrantRevoke(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class CapabilityCallRequest(BaseModel):
    """What a *external* agent sends to the boundary.

    ``capability`` is matched against the declared registry, never treated as
    a path to forward -- the schema is what makes "ACT does not proxy
    arbitrary traffic" true at the edge as well as in the service."""

    capability: str = Field(max_length=64)
    target_ref: str | None = Field(default=None, max_length=255)
    params: dict[str, Any] | None = None


class CapabilityCallResponse(BaseModel):
    call_id: uuid.UUID
    outcome: Literal["ALLOWED", "DENIED"]
    capability: str
    enforcement_mode: str
    #: What ACT's decision did and did not cover. Always present on both an
    #: allow and a deny -- the bound is not a footnote for failures.
    enforcement_reach: str
    limits: str
    denial_reason: str | None = None
    fail_mode: str
    dispatch_status: str
    dispatch_detail: dict | None = None


class GatewayCallRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    grant_id: uuid.UUID | None
    capability_key: str
    target_ref: str | None
    enforcement_mode_at_time: str
    authz_decision: str
    authz_permission: str
    authz_reason: str | None
    policy_outcome: str
    policy_detail: dict | None
    cost_outcome: str
    cost_detail: dict | None
    outcome: str
    denial_reason: str | None
    fail_mode: str
    dispatch_status: str
    dispatch_detail: dict | None
    created_at: datetime


class ObservedEvent(BaseModel):
    event_type: str = Field(min_length=1, max_length=100)
    payload: dict[str, Any] | None = None


class ObservedIngestRequest(BaseModel):
    events: list[ObservedEvent] = Field(min_length=1, max_length=50)


class ObservedIngestResponse(BaseModel):
    accepted: int
    dropped: int
    #: Always ``False``. Present in the contract, not just the implementation,
    #: so no consumer can read an ingest as an enforcement action.
    enforcement_performed: bool = False


class AdvisoryResponse(BaseModel):
    finding: str
    detail: dict[str, Any]
    enforcement_performed: bool = False


__all__ = [
    "SETTABLE_MODES",
    "EnforcementModeRead",
    "EnforcementModeSet",
    "GrantScopeEntry",
    "GrantCreate",
    "GrantRead",
    "GrantIssued",
    "GrantRevoke",
    "CapabilityCallRequest",
    "CapabilityCallResponse",
    "GatewayCallRead",
    "ObservedEvent",
    "ObservedIngestRequest",
    "ObservedIngestResponse",
    "AdvisoryResponse",
]
