"""Pydantic schemas for the governance API (Phase 4.3.8 §19)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- #
# SoD / toxic-permission rules (§9, §10)
# --------------------------------------------------------------------------- #
_RULE_TYPE = Field(pattern="^(SOD|TOXIC_PERMISSION)$")
_RISK_LEVEL = Field(pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")


class SoDRuleCreate(BaseModel):
    rule_type: str = Field(default="SOD", pattern="^(SOD|TOXIC_PERMISSION)$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    risk_level: str = Field(default="MEDIUM", pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    permissions_a: list[str] = Field(min_length=1)
    permissions_b: list[str] = Field(min_length=1)
    scope: dict | None = None


class SoDRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    risk_level: str | None = Field(default=None, pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    permissions_a: list[str] | None = None
    permissions_b: list[str] | None = None
    scope: dict | None = None


class SoDRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    rule_type: str
    name: str
    description: str | None
    risk_level: str
    permissions_a: list[str]
    permissions_b: list[str]
    scope: dict | None
    status: str
    created_by: uuid.UUID | None
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Governance findings (§17)
# --------------------------------------------------------------------------- #
class GovernanceFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    finding_type: str
    severity: str
    identity_id: uuid.UUID | None
    identity_label: str | None
    resource_id: uuid.UUID | None
    rule_id: uuid.UUID | None
    details: dict | None
    status: str
    detected_at: datetime
    resolved_at: datetime | None
    resolved_by: uuid.UUID | None


class FindingResolve(BaseModel):
    status: str = Field(pattern="^(ACKNOWLEDGED|REMEDIATED|DISMISSED)$")
    comment: str | None = Field(default=None, max_length=500)


# --------------------------------------------------------------------------- #
# Remediation (§14, §17)
# --------------------------------------------------------------------------- #
class RemediationActionCreate(BaseModel):
    finding_id: uuid.UUID
    action_type: str = Field(pattern="^(REMOVE_ROLE|DISABLE_ACCOUNT|DISABLE_API_KEY|"
                                      "EXPIRE_DELEGATION|NOTIFY_MANAGER|"
                                      "CREATE_APPROVAL_REQUEST|REQUIRE_MFA|"
                                      "CREATE_SECURITY_TICKET)$")
    mode: str = Field(default="MANUAL", pattern="^(MANUAL|APPROVAL|AUTOMATIC)$")
    payload: dict | None = None


class RemediationActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    finding_id: uuid.UUID
    action_type: str
    status: str
    mode: str
    payload: dict | None
    created_by: uuid.UUID | None
    approved_by: uuid.UUID | None
    executed_by: uuid.UUID | None
    executed_at: datetime | None
    created_at: datetime


# --------------------------------------------------------------------------- #
# Risk scoring (§13)
# --------------------------------------------------------------------------- #
class GovernanceRiskScoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    identity_id: uuid.UUID
    identity_label: str
    score: int
    band: str
    factors: dict | None
    computed_at: datetime


# --------------------------------------------------------------------------- #
# Privileged access governance (§11)
# --------------------------------------------------------------------------- #
class PrivilegedAccountRead(BaseModel):
    identity_id: uuid.UUID
    identity_label: str
    role_name: str
    assignment_id: uuid.UUID | None
    risk_score: int
    risk_band: str
    last_activity_at: datetime | None
    review_status: str | None
    review_due_at: datetime | None


class PrivilegedReviewDecision(BaseModel):
    decision: str = Field(pattern="^(APPROVED|REVOKED)$")
    comment: str | None = Field(default=None, max_length=500)


# --------------------------------------------------------------------------- #
# Orphaned identities (§12)
# --------------------------------------------------------------------------- #
class OrphanedScanResult(BaseModel):
    scanned_users: int
    scanned_api_keys: int
    scanned_roles: int
    findings_created: int


# --------------------------------------------------------------------------- #
# Compliance reporting (§15, §16)
# --------------------------------------------------------------------------- #
class ComplianceReportGenerate(BaseModel):
    framework: str = Field(pattern="^(SOC2|ISO27001|HIPAA|GDPR|NIST|CIS|INTERNAL)$")
    report_type: str = Field(default="EVIDENCE_SNAPSHOT", max_length=50)
    scope: dict | None = None


class ComplianceReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    framework: str
    report_type: str
    scope: dict | None
    payload: dict
    version: str
    generated_by: uuid.UUID | None
    generated_at: datetime


class ComplianceFrameworkRead(BaseModel):
    framework: str
    display_name: str
    controls: list[dict]  # [{control, platform_evidence}]


# --------------------------------------------------------------------------- #
# Governance dashboard & analytics (§21, §26)
# --------------------------------------------------------------------------- #
class GovernanceDashboardRead(BaseModel):
    widgets: dict
    charts: dict


class GovernanceAnalyticsRead(BaseModel):
    review_completion_trend: list[dict]
    findings_by_severity: list[dict]
    privileged_access_growth: list[dict]
    risk_score_distribution: list[dict]
    findings_by_type: list[dict]


# --------------------------------------------------------------------------- #
# Certification campaigns proxy (§5, §6, §7, §19) — thin wrapper around the
# Phase 4.3.7 AccessReviewService; extends decisions with MODIFIED/DELEGATED.
# --------------------------------------------------------------------------- #
class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    campaign_type: str = Field(default="QUARTERLY",
                                pattern="^(QUARTERLY|ANNUAL|PRIVILEGED|PROJECT|EMERGENCY)$")
    scope: dict | None = None
    reviewer_id: uuid.UUID | None = None
    due_at: datetime | None = None


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    campaign_type: str | None = Field(default=None,
                                       pattern="^(QUARTERLY|ANNUAL|PRIVILEGED|PROJECT|EMERGENCY)$")
    scope: dict | None = None
    reviewer_id: uuid.UUID | None = None
    due_at: datetime | None = None


class CampaignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None
    campaign_type: str
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


class ReviewDecision(BaseModel):
    comment: str | None = Field(default=None, max_length=500)
    delegate_to: uuid.UUID | None = None
