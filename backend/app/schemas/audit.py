"""Audit & Compliance Center schemas (Phase 3 Part 3.5).

These power the enriched audit views: severity / decision / status / actor name
are *derived* from the existing ``audit_logs`` rows (see ``audit_view``) — no new
columns are stored.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AuditEventListItem(BaseModel):
    """A row in the audit table (enriched & ready to render)."""

    id: uuid.UUID
    created_at: datetime
    event_type: str
    category: str
    actor_type: str
    actor_id: uuid.UUID | None
    actor_name: str | None
    resource: str | None
    action: str | None
    decision: str | None
    severity: str
    status: str
    entity_type: str
    entity_id: uuid.UUID | None
    request_id: str | None


class AuditRelatedEvent(BaseModel):
    id: uuid.UUID
    event_type: str
    actor_name: str | None
    created_at: datetime
    severity: str


class AuditEventDetail(AuditEventListItem):
    """Full forensic detail for a single event."""

    correlation_id: str | None = None
    session_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    reason: str | None = None
    policy: str | None = None
    approval_id: uuid.UUID | None = None
    risk_score: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Raw payloads are only populated for users holding ``audit.export``.
    request_payload: dict[str, Any] | None = None
    response_payload: dict[str, Any] | None = None
    related_events: list[AuditRelatedEvent] = Field(default_factory=list)


class AuditTimelineItem(BaseModel):
    id: uuid.UUID
    created_at: datetime
    event_type: str
    severity: str
    actor_name: str | None
    label: str


class AuditStatistics(BaseModel):
    total_events: int
    security_events: int
    policy_evaluations: int
    approval_events: int
    authentication_events: int
    configuration_changes: int


class AuditEventTypeInfo(BaseModel):
    """Catalog entry used to populate filter dropdowns and the type reference."""

    value: str
    label: str
    category: str
    severity: str


class AuditSecuritySummary(BaseModel):
    failed_logins: int
    blocked_agents: int
    disabled_api_keys: int
    permission_violations: int
    suspicious_activity: int
    critical_alerts: int
    recent: list[AuditEventListItem] = Field(default_factory=list)


class ComplianceMetric(BaseModel):
    label: str
    score: int  # 0-100
    status: str  # e.g. "Ready", "In progress", "Attention"
    detail: str


class AuditComplianceSummary(BaseModel):
    hipaa_readiness: ComplianceMetric
    soc2_readiness: ComplianceMetric
    iso27001_controls: ComplianceMetric
    policy_coverage: ComplianceMetric
    approval_coverage: ComplianceMetric
    audit_completeness: ComplianceMetric
