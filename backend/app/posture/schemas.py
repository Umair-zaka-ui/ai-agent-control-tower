"""Pydantic schemas for the Phase 5.5 (M5.5) security-posture API.

Read-and-triage only. A client never submits a finding (findings are derived
deterministically from evidence, never client-submitted - §9 threat model);
the only writes are lifecycle transitions on an existing finding and
per-tenant rule settings.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    rule_id: str
    control_id: str | None
    rule_version: str
    ruleset_version: str
    outcome: str
    severity: str
    status: str
    subject_type: str
    subject_id: uuid.UUID
    reason: str
    remediation: str
    evidence: dict
    governing_policy: dict
    recurrence_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    suppressed_at: datetime | None


class FindingTransition(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class RuleSettingUpdate(BaseModel):
    enabled: bool | None = None
    params: dict | None = None


class RuleSettingRead(BaseModel):
    rule_id: str
    control_id: str
    default_severity: str
    shadow_class: bool
    rule_version: str
    summary: str
    default_params: dict
    enabled: bool
    effective_params: dict
    settings_revision: int


__all__ = [
    "FindingRead",
    "FindingTransition",
    "RuleSettingUpdate",
    "RuleSettingRead",
]
