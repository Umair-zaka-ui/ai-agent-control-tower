"""Request/response DTOs for the account-protection API (4.2.2.3.4 §20)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# --- Read models ----------------------------------------------------------- #
class LoginAttemptRead(BaseModel):
    id: uuid.UUID
    email: str
    success: bool
    failure_reason: str | None = None
    ip_address: str | None = None
    country: str | None = None
    city: str | None = None
    user_agent: str | None = None
    device_fingerprint: str | None = None
    risk_score: int | None = None
    decision: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RiskEventRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None = None
    event_type: str
    risk_score: int
    risk_level: str
    signals: dict
    decision: str
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AccountLockRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    organization_id: uuid.UUID
    reason: str
    status: str
    locked_at: datetime
    expires_at: datetime | None = None
    unlocked_at: datetime | None = None
    unlocked_by: uuid.UUID | None = None
    meta: dict
    created_at: datetime
    # Joined for the table (§24).
    user_email: str | None = None
    risk_score: int | None = None

    model_config = {"from_attributes": True}


class BlockedIpRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    ip_address: str
    reason: str | None = None
    expires_at: datetime | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ProtectionRuleRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None = None
    conditions: list[dict]
    decision: str
    enabled: bool
    priority: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Write models ---------------------------------------------------------- #
class UnlockRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=255)
    comment: str | None = None


class LockUserRequest(BaseModel):
    reason: str = "ADMIN_LOCKED"
    comment: str | None = None


class BlockIpRequest(BaseModel):
    ip_address: str = Field(min_length=3, max_length=64)
    reason: str | None = None
    # Minutes until the block lapses; omit for a permanent block.
    expires_in_minutes: int | None = None
    # NULL scope = a platform-wide block; only allowed with the right role.
    global_scope: bool = False


class ProtectionRuleWrite(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    conditions: list[dict] = Field(default_factory=list)
    decision: str
    enabled: bool = True
    priority: int = 100


class ProtectionRuleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    conditions: list[dict] | None = None
    decision: str | None = None
    enabled: bool | None = None
    priority: int | None = None


class ProtectionSummary(BaseModel):
    """Security-dashboard widgets (§23)."""

    failed_logins_today: int
    locked_accounts: int
    high_risk_attempts: int
    blocked_ips: int
    active_rules: int
    risk_events_recent: int
