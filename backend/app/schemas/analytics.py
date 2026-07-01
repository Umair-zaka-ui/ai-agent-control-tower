"""Analytics & AI Operations Center schemas (Phase 3 Part 3.6).

These power the executive/operations analytics surfaces. Everything is *derived*
at read time from existing rows (agents, agent_actions, approvals, policies,
audit_logs) — no new tables. Where the platform does not record a real signal
(e.g. per-action latency), the value is a deterministic estimate and is labelled
as such in ``analytics_service``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# KPIs
# --------------------------------------------------------------------------- #
class KpiMetric(BaseModel):
    """A single executive KPI tile (value + trend)."""

    key: str
    label: str
    value: float
    unit: str = ""  # "", "%", "ms", "s"
    change_pct: float | None = None  # period-over-period change, None if N/A
    direction: str = "flat"  # "up" | "down" | "flat"
    positive_is_good: bool = True  # whether an "up" direction is good
    estimated: bool = False


# --------------------------------------------------------------------------- #
# Fleet health
# --------------------------------------------------------------------------- #
class FleetHealth(BaseModel):
    total: int
    healthy: int
    warning: int
    offline: int
    active: int
    inactive: int
    suspended: int
    archived: int
    blocked: int


# --------------------------------------------------------------------------- #
# Activity
# --------------------------------------------------------------------------- #
class ActivityPoint(BaseModel):
    period: str
    executed: int
    blocked: int
    approvals: int
    rejections: int
    escalations: int
    failures: int


# --------------------------------------------------------------------------- #
# Risk
# --------------------------------------------------------------------------- #
class RiskBands(BaseModel):
    low: int
    medium: int
    high: int
    critical: int


class RiskTrendPoint(BaseModel):
    date: str
    risk_score: int


class RiskGroup(BaseModel):
    label: str
    avg_risk: int
    count: int


class RiskHeatmapRow(BaseModel):
    label: str
    low: int
    medium: int
    high: int
    critical: int


class HighRiskAgent(BaseModel):
    agent_id: uuid.UUID
    name: str | None
    agent_type: str | None
    avg_risk: int
    action_count: int
    health: str


class RiskAnalytics(BaseModel):
    distribution: RiskBands
    trend: list[RiskTrendPoint] = Field(default_factory=list)
    by_department: list[RiskGroup] = Field(default_factory=list)
    by_agent_type: list[RiskGroup] = Field(default_factory=list)
    heatmap: list[RiskHeatmapRow] = Field(default_factory=list)
    high_risk_agents: list[HighRiskAgent] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Performance
# --------------------------------------------------------------------------- #
class PerformanceMetrics(BaseModel):
    avg_response_time_ms: int
    execution_time_ms: int
    decision_latency_ms: int
    policy_eval_time_ms: int
    approval_delay_seconds: int
    avg_processing_time_ms: int
    failure_rate: float
    retry_rate: float
    estimated: bool = True


class AgentRanking(BaseModel):
    rank: int
    agent_id: uuid.UUID
    name: str | None
    agent_type: str | None
    requests: int
    success_pct: float
    failures: int
    avg_risk: int
    avg_response_ms: int
    health: str


class PerformanceAnalytics(BaseModel):
    metrics: PerformanceMetrics
    ranking: list[AgentRanking] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Policy analytics
# --------------------------------------------------------------------------- #
class PolicyStat(BaseModel):
    policy_id: uuid.UUID
    name: str
    decision: str
    trigger_count: int
    severity: str
    enabled: bool


class PolicyAnalytics(BaseModel):
    most_triggered: list[PolicyStat] = Field(default_factory=list)
    least_used: list[PolicyStat] = Field(default_factory=list)
    most_blocking: list[PolicyStat] = Field(default_factory=list)
    most_approval: list[PolicyStat] = Field(default_factory=list)
    total_policies: int
    enabled_policies: int
    effectiveness_pct: int
    false_positive_rate: float
    coverage_pct: int


# --------------------------------------------------------------------------- #
# Human review analytics
# --------------------------------------------------------------------------- #
class ReviewerStat(BaseModel):
    user_id: uuid.UUID
    name: str | None
    assigned: int
    reviewed: int
    approved: int
    rejected: int
    avg_review_seconds: int


class HumanReviewAnalytics(BaseModel):
    avg_approval_time_seconds: int
    pending_queue: int
    escalation_rate: float
    approval_ratio: float
    rejection_ratio: float
    reviewers: list[ReviewerStat] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Cost analytics (estimated)
# --------------------------------------------------------------------------- #
class CostItem(BaseModel):
    key: str
    label: str
    amount: float
    unit: str = "USD"


class CostAnalytics(BaseModel):
    items: list[CostItem] = Field(default_factory=list)
    total: float
    currency: str = "USD"
    period_label: str
    estimated: bool = True


# --------------------------------------------------------------------------- #
# Insights (rule-based)
# --------------------------------------------------------------------------- #
class Insight(BaseModel):
    id: str
    title: str
    detail: str
    tone: str = "neutral"  # "positive" | "negative" | "neutral"
    metric: str | None = None


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
class ReportRow(BaseModel):
    label: str
    value: str


class ReportSection(BaseModel):
    title: str
    rows: list[ReportRow] = Field(default_factory=list)


class AnalyticsReport(BaseModel):
    period: str
    label: str
    generated_at: datetime
    sections: list[ReportSection] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Overview (composite for the landing dashboard)
# --------------------------------------------------------------------------- #
class AnalyticsOverview(BaseModel):
    generated_at: datetime
    kpis: list[KpiMetric] = Field(default_factory=list)
    fleet_health: FleetHealth
    risk_distribution: RiskBands
    activity: list[ActivityPoint] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
