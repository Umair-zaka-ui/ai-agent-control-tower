"""Analytics & AI Operations Center service (Phase 3 Part 3.6).

Aggregates the existing operational tables (agents, agent_actions, approvals,
policies, audit_logs) into the executive / operations analytics surfaces. Pure
read + projection — nothing here writes.

Real signals (counts, averages, approval delays, risk) are computed from the
data. The platform does not record per-action latency or LLM/compute spend, so
those are *deterministic estimates* derived from the real aggregates and flagged
with ``estimated=True`` on the response models.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.enums import (
    ActionDecision,
    ActionStatus,
    AgentStatus,
    ApprovalDecision,
)
from app.models.agent import Agent
from app.models.agent_action import AgentAction
from app.models.approval import Approval
from app.models.audit_log import AuditLog
from app.models.policy import Policy
from app.models.user import User
from app.schemas.analytics import (
    ActivityPoint,
    AgentRanking,
    AnalyticsOverview,
    AnalyticsReport,
    CostAnalytics,
    CostItem,
    FleetHealth,
    HighRiskAgent,
    HumanReviewAnalytics,
    Insight,
    KpiMetric,
    PerformanceAnalytics,
    PerformanceMetrics,
    PolicyAnalytics,
    PolicyStat,
    ReportRow,
    ReportSection,
    ReviewerStat,
    RiskAnalytics,
    RiskBands,
    RiskGroup,
    RiskHeatmapRow,
    RiskTrendPoint,
)

# Risk bands (mirror the frontend riskLevel ladder / audit derivation).
_LOW_MAX = 30
_MED_MAX = 60
_HIGH_MAX = 80

# Estimated unit costs (USD) for the cost dashboard — deterministic placeholders.
_COST_PER_ACTION = 0.012
_COST_PER_POLICY_EVAL = 0.0008
_COST_PER_LLM_ACTION = 0.03
_HUMAN_REVIEW_HOURLY = 65.0
_HUMAN_REVIEW_MINUTES = 6.0
_COST_PER_AUDIT_ROW_GB = 0.0000005


def _utc_day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _count(db: Session, stmt) -> int:
    return db.execute(stmt).scalar_one() or 0


def _pct_change(curr: float, prev: float) -> tuple[float | None, str]:
    """Period-over-period percentage change + direction."""
    if prev == 0:
        if curr == 0:
            return 0.0, "flat"
        return None, "up"  # no baseline to compute against
    change = round((curr - prev) / prev * 100, 1)
    direction = "up" if change > 0 else "down" if change < 0 else "flat"
    return change, direction


def _risk_band(score: float) -> str:
    if score <= _LOW_MAX:
        return "low"
    if score <= _MED_MAX:
        return "medium"
    if score <= _HIGH_MAX:
        return "high"
    return "critical"


# --------------------------------------------------------------------------- #
# KPIs
# --------------------------------------------------------------------------- #
def kpis(db: Session, org: uuid.UUID) -> list[KpiMetric]:
    now = datetime.now(timezone.utc)
    today = _utc_day_start(now)
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)
    two_weeks_ago = today - timedelta(days=14)

    total_agents = _count(db, select(func.count(Agent.id)).where(Agent.organization_id == org))
    active_agents = _count(
        db,
        select(func.count(Agent.id)).where(
            Agent.organization_id == org, Agent.status == AgentStatus.ACTIVE
        ),
    )
    total_policies = _count(db, select(func.count(Policy.id)).where(Policy.organization_id == org))

    actions_today = _count(
        db,
        select(func.count(AgentAction.id)).where(
            AgentAction.organization_id == org, AgentAction.created_at >= today
        ),
    )
    actions_yesterday = _count(
        db,
        select(func.count(AgentAction.id)).where(
            AgentAction.organization_id == org,
            AgentAction.created_at >= yesterday,
            AgentAction.created_at < today,
        ),
    )
    approvals_today = _count(
        db,
        select(func.count(Approval.id)).where(
            Approval.organization_id == org, Approval.reviewed_at >= today
        ),
    )
    approvals_yesterday = _count(
        db,
        select(func.count(Approval.id)).where(
            Approval.organization_id == org,
            Approval.reviewed_at >= yesterday,
            Approval.reviewed_at < today,
        ),
    )

    total_actions = _count(
        db, select(func.count(AgentAction.id)).where(AgentAction.organization_id == org)
    )
    allowed = _count(
        db,
        select(func.count(AgentAction.id)).where(
            AgentAction.organization_id == org, AgentAction.decision == ActionDecision.ALLOW
        ),
    )
    blocked = _count(
        db,
        select(func.count(AgentAction.id)).where(
            AgentAction.organization_id == org, AgentAction.decision == ActionDecision.BLOCK
        ),
    )
    success_rate = round(allowed / total_actions * 100, 1) if total_actions else 0.0
    failure_rate = round(blocked / total_actions * 100, 1) if total_actions else 0.0

    avg_risk = round(
        db.execute(
            select(func.avg(AgentAction.risk_score)).where(AgentAction.organization_id == org)
        ).scalar()
        or 0
    )
    avg_risk_week = _avg_risk_between(db, org, week_ago, today)
    avg_risk_prev = _avg_risk_between(db, org, two_weeks_ago, week_ago)

    compliance = _compliance_score(db, org)
    # Estimated: no per-action timing is recorded.
    avg_decision_ms = 120 + avg_risk * 4

    actions_change, actions_dir = _pct_change(actions_today, actions_yesterday)
    approvals_change, approvals_dir = _pct_change(approvals_today, approvals_yesterday)
    risk_change, risk_dir = _pct_change(avg_risk_week, avg_risk_prev)

    return [
        KpiMetric(key="total_agents", label="Total AI Agents", value=total_agents, unit=""),
        KpiMetric(key="active_agents", label="Active Agents", value=active_agents, unit=""),
        KpiMetric(
            key="actions_today",
            label="AI Actions Today",
            value=actions_today,
            change_pct=actions_change,
            direction=actions_dir,
        ),
        KpiMetric(
            key="approvals_today",
            label="Human Approvals Today",
            value=approvals_today,
            change_pct=approvals_change,
            direction=approvals_dir,
        ),
        KpiMetric(
            key="success_rate", label="AI Success Rate", value=success_rate, unit="%"
        ),
        KpiMetric(
            key="failure_rate",
            label="AI Failure Rate",
            value=failure_rate,
            unit="%",
            positive_is_good=False,
        ),
        KpiMetric(
            key="avg_risk_score",
            label="Average Risk Score",
            value=avg_risk,
            change_pct=risk_change,
            direction=risk_dir,
            positive_is_good=False,
        ),
        KpiMetric(
            key="avg_decision_time",
            label="Avg Decision Time",
            value=avg_decision_ms,
            unit="ms",
            positive_is_good=False,
            estimated=True,
        ),
        KpiMetric(key="total_policies", label="Total Policies", value=total_policies, unit=""),
        KpiMetric(
            key="compliance_score", label="Compliance Score", value=compliance, unit="%"
        ),
    ]


def _avg_risk_between(db: Session, org: uuid.UUID, start: datetime, end: datetime) -> float:
    return float(
        db.execute(
            select(func.avg(AgentAction.risk_score)).where(
                AgentAction.organization_id == org,
                AgentAction.created_at >= start,
                AgentAction.created_at < end,
            )
        ).scalar()
        or 0
    )


def _compliance_score(db: Session, org: uuid.UUID) -> int:
    total_policies = _count(db, select(func.count(Policy.id)).where(Policy.organization_id == org))
    enabled = _count(
        db,
        select(func.count(Policy.id)).where(
            Policy.organization_id == org, Policy.enabled.is_(True)
        ),
    )
    approvals = _count(db, select(func.count(Approval.id)).where(Approval.organization_id == org))
    audit_rows = _count(db, select(func.count(AuditLog.id)).where(AuditLog.organization_id == org))
    policy_pct = (enabled / total_policies * 100) if total_policies else 0
    approval_pct = 100 if approvals else 0
    audit_pct = 100 if audit_rows else 0
    return round((policy_pct + approval_pct + audit_pct) / 3)


# --------------------------------------------------------------------------- #
# Fleet health
# --------------------------------------------------------------------------- #
def fleet_health(db: Session, org: uuid.UUID) -> FleetHealth:
    rows = db.execute(
        select(Agent.status, Agent.health).where(Agent.organization_id == org)
    ).all()
    health_counts = {"HEALTHY": 0, "WARNING": 0, "OFFLINE": 0}
    status_counts = {s.value: 0 for s in AgentStatus}
    for status, health in rows:
        status_key = status.value if hasattr(status, "value") else str(status)
        status_counts[status_key] = status_counts.get(status_key, 0) + 1
        health_counts[str(health)] = health_counts.get(str(health), 0) + 1
    return FleetHealth(
        total=len(rows),
        healthy=health_counts.get("HEALTHY", 0),
        warning=health_counts.get("WARNING", 0),
        offline=health_counts.get("OFFLINE", 0),
        active=status_counts.get("ACTIVE", 0),
        inactive=status_counts.get("INACTIVE", 0),
        suspended=status_counts.get("SUSPENDED", 0),
        archived=status_counts.get("ARCHIVED", 0),
        blocked=status_counts.get("BLOCKED", 0),
    )


# --------------------------------------------------------------------------- #
# Activity
# --------------------------------------------------------------------------- #
_RANGES: dict[str, tuple[str, int]] = {
    "daily": ("day", 14),
    "weekly": ("week", 12),
    "monthly": ("month", 12),
    "yearly": ("year", 5),
}


def _bucket_starts(unit: str, count: int, now: datetime) -> list[datetime]:
    today = _utc_day_start(now)
    starts: list[datetime] = []
    if unit == "day":
        base = today
        for i in range(count - 1, -1, -1):
            starts.append(base - timedelta(days=i))
    elif unit == "week":
        monday = today - timedelta(days=today.weekday())
        for i in range(count - 1, -1, -1):
            starts.append(monday - timedelta(weeks=i))
    elif unit == "month":
        y, m = today.year, today.month
        seq = []
        for _ in range(count):
            seq.append(datetime(y, m, 1, tzinfo=timezone.utc))
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        starts = list(reversed(seq))
    elif unit == "year":
        for i in range(count - 1, -1, -1):
            starts.append(datetime(today.year - i, 1, 1, tzinfo=timezone.utc))
    return starts


def _label(unit: str, d: date) -> str:
    if unit == "day":
        return d.strftime("%b %d")
    if unit == "week":
        return d.strftime("%b %d")
    if unit == "month":
        return d.strftime("%b %Y")
    return d.strftime("%Y")


def activity(db: Session, org: uuid.UUID, range_key: str = "daily") -> list[ActivityPoint]:
    unit, count = _RANGES.get(range_key, _RANGES["daily"])
    now = datetime.now(timezone.utc)
    starts = _bucket_starts(unit, count, now)
    window_start = starts[0]
    bucket = func.date_trunc(unit, func.timezone("UTC", AgentAction.created_at))

    action_rows = db.execute(
        select(
            bucket.label("b"),
            func.sum(
                case(
                    (
                        (AgentAction.decision == ActionDecision.ALLOW)
                        | (AgentAction.status == ActionStatus.EXECUTED),
                        1,
                    ),
                    else_=0,
                )
            ),
            func.sum(case((AgentAction.decision == ActionDecision.BLOCK, 1), else_=0)),
            func.sum(case((AgentAction.status == ActionStatus.REJECTED, 1), else_=0)),
        )
        .where(AgentAction.organization_id == org, AgentAction.created_at >= window_start)
        .group_by(bucket)
    ).all()
    executed_map: dict[date, int] = {}
    blocked_map: dict[date, int] = {}
    failures_map: dict[date, int] = {}
    for b, ex, bl, fa in action_rows:
        key = b.date() if isinstance(b, datetime) else b
        executed_map[key] = int(ex or 0)
        blocked_map[key] = int(bl or 0)
        failures_map[key] = int(fa or 0)

    # Approvals by reviewed_at (approved / rejected) and escalated_at (escalations).
    rbucket = func.date_trunc(unit, func.timezone("UTC", Approval.reviewed_at))
    approval_rows = db.execute(
        select(
            rbucket.label("b"),
            func.sum(case((Approval.decision == ApprovalDecision.APPROVED, 1), else_=0)),
            func.sum(case((Approval.decision == ApprovalDecision.REJECTED, 1), else_=0)),
        )
        .where(
            Approval.organization_id == org,
            Approval.reviewed_at.is_not(None),
            Approval.reviewed_at >= window_start,
        )
        .group_by(rbucket)
    ).all()
    approvals_map: dict[date, int] = {}
    rejections_map: dict[date, int] = {}
    for b, ap, rj in approval_rows:
        key = b.date() if isinstance(b, datetime) else b
        approvals_map[key] = int(ap or 0)
        rejections_map[key] = int(rj or 0)

    ebucket = func.date_trunc(unit, func.timezone("UTC", Approval.escalated_at))
    esc_rows = db.execute(
        select(ebucket.label("b"), func.count(Approval.id))
        .where(
            Approval.organization_id == org,
            Approval.escalated_at.is_not(None),
            Approval.escalated_at >= window_start,
        )
        .group_by(ebucket)
    ).all()
    escalations_map: dict[date, int] = {
        (b.date() if isinstance(b, datetime) else b): int(n or 0) for b, n in esc_rows
    }

    series: list[ActivityPoint] = []
    for start in starts:
        key = start.date()
        series.append(
            ActivityPoint(
                period=_label(unit, key),
                executed=executed_map.get(key, 0),
                blocked=blocked_map.get(key, 0),
                approvals=approvals_map.get(key, 0),
                rejections=rejections_map.get(key, 0),
                escalations=escalations_map.get(key, 0),
                failures=failures_map.get(key, 0),
            )
        )
    return series


# --------------------------------------------------------------------------- #
# Risk
# --------------------------------------------------------------------------- #
def risk_analytics(db: Session, org: uuid.UUID) -> RiskAnalytics:
    band_expr = case(
        (AgentAction.risk_score <= _LOW_MAX, "low"),
        (AgentAction.risk_score <= _MED_MAX, "medium"),
        (AgentAction.risk_score <= _HIGH_MAX, "high"),
        else_="critical",
    )
    band_rows = db.execute(
        select(band_expr.label("band"), func.count(AgentAction.id))
        .where(AgentAction.organization_id == org)
        .group_by(band_expr)
    ).all()
    bands = {b: int(n) for b, n in band_rows}
    distribution = RiskBands(
        low=bands.get("low", 0),
        medium=bands.get("medium", 0),
        high=bands.get("high", 0),
        critical=bands.get("critical", 0),
    )

    trend = _risk_trend(db, org, days=30)

    by_department = _risk_by_group(db, org, Agent.department)
    by_agent_type = _risk_by_group(db, org, Agent.agent_type)
    heatmap = _risk_heatmap(db, org)
    high_risk = _high_risk_agents(db, org)

    return RiskAnalytics(
        distribution=distribution,
        trend=trend,
        by_department=by_department,
        by_agent_type=by_agent_type,
        heatmap=heatmap,
        high_risk_agents=high_risk,
    )


def _risk_trend(db: Session, org: uuid.UUID, days: int) -> list[RiskTrendPoint]:
    today = _utc_day_start(datetime.now(timezone.utc))
    start = today - timedelta(days=days - 1)
    rows = db.execute(
        select(
            func.date(func.timezone("UTC", AgentAction.created_at)).label("day"),
            func.avg(AgentAction.risk_score),
        )
        .where(AgentAction.organization_id == org, AgentAction.created_at >= start)
        .group_by(func.date(func.timezone("UTC", AgentAction.created_at)))
    ).all()
    averages = {str(day): float(avg or 0) for day, avg in rows}
    series: list[RiskTrendPoint] = []
    for offset in range(days):
        day = (start + timedelta(days=offset)).date()
        series.append(
            RiskTrendPoint(date=day.isoformat(), risk_score=round(averages.get(str(day), 0)))
        )
    return series


def _risk_by_group(db: Session, org: uuid.UUID, column) -> list[RiskGroup]:
    rows = db.execute(
        select(column, func.avg(AgentAction.risk_score), func.count(AgentAction.id))
        .join(Agent, Agent.id == AgentAction.agent_id)
        .where(AgentAction.organization_id == org)
        .group_by(column)
        .order_by(func.avg(AgentAction.risk_score).desc())
    ).all()
    groups: list[RiskGroup] = []
    for label, avg, cnt in rows:
        groups.append(
            RiskGroup(label=label or "Unassigned", avg_risk=round(float(avg or 0)), count=int(cnt))
        )
    return groups


def _risk_heatmap(db: Session, org: uuid.UUID) -> list[RiskHeatmapRow]:
    band_expr = case(
        (AgentAction.risk_score <= _LOW_MAX, "low"),
        (AgentAction.risk_score <= _MED_MAX, "medium"),
        (AgentAction.risk_score <= _HIGH_MAX, "high"),
        else_="critical",
    )
    rows = db.execute(
        select(Agent.agent_type, band_expr.label("band"), func.count(AgentAction.id))
        .join(Agent, Agent.id == AgentAction.agent_id)
        .where(AgentAction.organization_id == org)
        .group_by(Agent.agent_type, band_expr)
    ).all()
    matrix: dict[str, dict[str, int]] = {}
    for agent_type, band, cnt in rows:
        key = agent_type or "Unknown"
        matrix.setdefault(key, {"low": 0, "medium": 0, "high": 0, "critical": 0})
        matrix[key][band] = int(cnt)
    return [
        RiskHeatmapRow(label=k, low=v["low"], medium=v["medium"], high=v["high"], critical=v["critical"])
        for k, v in sorted(matrix.items())
    ]


def _high_risk_agents(db: Session, org: uuid.UUID, limit: int = 8) -> list[HighRiskAgent]:
    rows = db.execute(
        select(
            Agent.id,
            Agent.name,
            Agent.agent_type,
            Agent.health,
            func.avg(AgentAction.risk_score),
            func.count(AgentAction.id),
        )
        .join(AgentAction, AgentAction.agent_id == Agent.id)
        .where(Agent.organization_id == org)
        .group_by(Agent.id, Agent.name, Agent.agent_type, Agent.health)
        .order_by(func.avg(AgentAction.risk_score).desc())
        .limit(limit)
    ).all()
    return [
        HighRiskAgent(
            agent_id=aid,
            name=name,
            agent_type=atype,
            health=str(health),
            avg_risk=round(float(avg or 0)),
            action_count=int(cnt),
        )
        for aid, name, atype, health, avg, cnt in rows
    ]


# --------------------------------------------------------------------------- #
# Performance
# --------------------------------------------------------------------------- #
def performance_analytics(db: Session, org: uuid.UUID) -> PerformanceAnalytics:
    total = _count(db, select(func.count(AgentAction.id)).where(AgentAction.organization_id == org))
    blocked = _count(
        db,
        select(func.count(AgentAction.id)).where(
            AgentAction.organization_id == org, AgentAction.decision == ActionDecision.BLOCK
        ),
    )
    rejected = _count(
        db,
        select(func.count(AgentAction.id)).where(
            AgentAction.organization_id == org, AgentAction.status == ActionStatus.REJECTED
        ),
    )
    avg_risk = round(
        db.execute(
            select(func.avg(AgentAction.risk_score)).where(AgentAction.organization_id == org)
        ).scalar()
        or 0
    )
    approval_delay = _avg_approval_delay_seconds(db, org)

    failure_rate = round((blocked + rejected) / total * 100, 1) if total else 0.0
    decision_latency = 40 + avg_risk * 2
    policy_eval = 15 + avg_risk
    execution = 200 + avg_risk * 5
    avg_response = decision_latency + policy_eval + execution

    metrics = PerformanceMetrics(
        avg_response_time_ms=avg_response,
        execution_time_ms=execution,
        decision_latency_ms=decision_latency,
        policy_eval_time_ms=policy_eval,
        approval_delay_seconds=approval_delay,
        avg_processing_time_ms=avg_response,
        failure_rate=failure_rate,
        retry_rate=round(failure_rate * 0.3, 1),
        estimated=True,
    )
    return PerformanceAnalytics(metrics=metrics, ranking=_agent_ranking(db, org))


def _avg_approval_delay_seconds(db: Session, org: uuid.UUID) -> int:
    delta = func.avg(
        func.extract("epoch", Approval.reviewed_at) - func.extract("epoch", Approval.created_at)
    )
    value = db.execute(
        select(delta).where(
            Approval.organization_id == org, Approval.reviewed_at.is_not(None)
        )
    ).scalar()
    return round(float(value)) if value else 0


def _agent_ranking(db: Session, org: uuid.UUID, limit: int = 25) -> list[AgentRanking]:
    success_case = func.sum(
        case(
            (
                (AgentAction.decision == ActionDecision.ALLOW)
                | (AgentAction.status == ActionStatus.EXECUTED),
                1,
            ),
            else_=0,
        )
    )
    failure_case = func.sum(
        case(
            (
                (AgentAction.decision == ActionDecision.BLOCK)
                | (AgentAction.status == ActionStatus.REJECTED),
                1,
            ),
            else_=0,
        )
    )
    rows = db.execute(
        select(
            Agent.id,
            Agent.name,
            Agent.agent_type,
            Agent.health,
            func.count(AgentAction.id).label("requests"),
            success_case.label("success"),
            failure_case.label("failures"),
            func.avg(AgentAction.risk_score).label("avg_risk"),
        )
        .join(AgentAction, AgentAction.agent_id == Agent.id)
        .where(Agent.organization_id == org)
        .group_by(Agent.id, Agent.name, Agent.agent_type, Agent.health)
        .order_by(func.count(AgentAction.id).desc())
        .limit(limit)
    ).all()
    ranking: list[AgentRanking] = []
    for i, (aid, name, atype, health, requests, success, failures, avg_risk) in enumerate(rows, 1):
        req = int(requests or 0)
        avg_r = round(float(avg_risk or 0))
        ranking.append(
            AgentRanking(
                rank=i,
                agent_id=aid,
                name=name,
                agent_type=atype,
                requests=req,
                success_pct=round(int(success or 0) / req * 100, 1) if req else 0.0,
                failures=int(failures or 0),
                avg_risk=avg_r,
                avg_response_ms=150 + avg_r * 4,  # estimated
                health=str(health),
            )
        )
    return ranking


# --------------------------------------------------------------------------- #
# Policy analytics
# --------------------------------------------------------------------------- #
def policy_analytics(db: Session, org: uuid.UUID) -> PolicyAnalytics:
    policies = db.execute(select(Policy).where(Policy.organization_id == org)).scalars().all()
    total = len(policies)
    enabled = sum(1 for p in policies if p.enabled)
    triggered = sum(1 for p in policies if (p.trigger_count or 0) > 0)

    def stat(p: Policy) -> PolicyStat:
        return PolicyStat(
            policy_id=p.id,
            name=p.name,
            decision=p.decision,
            trigger_count=p.trigger_count or 0,
            severity=p.severity,
            enabled=p.enabled,
        )

    by_triggers = sorted(policies, key=lambda p: p.trigger_count or 0, reverse=True)
    most_triggered = [stat(p) for p in by_triggers[:8]]
    least_used = [stat(p) for p in sorted(policies, key=lambda p: p.trigger_count or 0)[:8]]
    most_blocking = [
        stat(p)
        for p in sorted(
            (p for p in policies if p.decision == "BLOCK"),
            key=lambda p: p.trigger_count or 0,
            reverse=True,
        )[:8]
    ]
    most_approval = [
        stat(p)
        for p in sorted(
            (p for p in policies if p.decision == "PENDING_APPROVAL"),
            key=lambda p: p.trigger_count or 0,
            reverse=True,
        )[:8]
    ]

    effectiveness = round(triggered / total * 100) if total else 0
    coverage = round(enabled / total * 100) if total else 0
    # Estimated: we cannot observe true false positives without execution outcomes.
    false_positive_rate = round(max(0.0, 100 - effectiveness) * 0.15, 1)

    return PolicyAnalytics(
        most_triggered=most_triggered,
        least_used=least_used,
        most_blocking=most_blocking,
        most_approval=most_approval,
        total_policies=total,
        enabled_policies=enabled,
        effectiveness_pct=effectiveness,
        false_positive_rate=false_positive_rate,
        coverage_pct=coverage,
    )


# --------------------------------------------------------------------------- #
# Human review analytics
# --------------------------------------------------------------------------- #
def human_review_analytics(db: Session, org: uuid.UUID) -> HumanReviewAnalytics:
    total = _count(db, select(func.count(Approval.id)).where(Approval.organization_id == org))
    approved = _count(
        db,
        select(func.count(Approval.id)).where(
            Approval.organization_id == org, Approval.decision == ApprovalDecision.APPROVED
        ),
    )
    rejected = _count(
        db,
        select(func.count(Approval.id)).where(
            Approval.organization_id == org, Approval.decision == ApprovalDecision.REJECTED
        ),
    )
    escalated = _count(
        db,
        select(func.count(Approval.id)).where(
            Approval.organization_id == org, Approval.decision == ApprovalDecision.ESCALATED
        ),
    )
    pending = _count(
        db,
        select(func.count(Approval.id)).where(
            Approval.organization_id == org, Approval.decision == ApprovalDecision.PENDING
        ),
    )
    resolved = approved + rejected
    return HumanReviewAnalytics(
        avg_approval_time_seconds=_avg_approval_delay_seconds(db, org),
        pending_queue=pending,
        escalation_rate=round(escalated / total * 100, 1) if total else 0.0,
        approval_ratio=round(approved / resolved * 100, 1) if resolved else 0.0,
        rejection_ratio=round(rejected / resolved * 100, 1) if resolved else 0.0,
        reviewers=_reviewer_stats(db, org),
    )


def _reviewer_stats(db: Session, org: uuid.UUID) -> list[ReviewerStat]:
    delay = func.avg(
        func.extract("epoch", Approval.reviewed_at) - func.extract("epoch", Approval.created_at)
    )
    rows = db.execute(
        select(
            User.id,
            User.name,
            func.count(Approval.id).label("reviewed"),
            func.sum(case((Approval.decision == ApprovalDecision.APPROVED, 1), else_=0)),
            func.sum(case((Approval.decision == ApprovalDecision.REJECTED, 1), else_=0)),
            delay,
        )
        .join(Approval, Approval.reviewed_by_user_id == User.id)
        .where(Approval.organization_id == org)
        .group_by(User.id, User.name)
        .order_by(func.count(Approval.id).desc())
    ).all()
    assigned_rows = db.execute(
        select(Approval.assigned_to_user_id, func.count(Approval.id))
        .where(Approval.organization_id == org, Approval.assigned_to_user_id.is_not(None))
        .group_by(Approval.assigned_to_user_id)
    ).all()
    assigned_map = {uid: int(n) for uid, n in assigned_rows}
    stats: list[ReviewerStat] = []
    for uid, name, reviewed, approved, rejected, avg_delay in rows:
        stats.append(
            ReviewerStat(
                user_id=uid,
                name=name,
                assigned=assigned_map.get(uid, 0),
                reviewed=int(reviewed or 0),
                approved=int(approved or 0),
                rejected=int(rejected or 0),
                avg_review_seconds=round(float(avg_delay)) if avg_delay else 0,
            )
        )
    return stats


# --------------------------------------------------------------------------- #
# Cost analytics (estimated)
# --------------------------------------------------------------------------- #
def cost_analytics(db: Session, org: uuid.UUID) -> CostAnalytics:
    total_actions = _count(
        db, select(func.count(AgentAction.id)).where(AgentAction.organization_id == org)
    )
    approvals = _count(db, select(func.count(Approval.id)).where(Approval.organization_id == org))
    policy_evals = (
        db.execute(
            select(func.coalesce(func.sum(Policy.trigger_count), 0)).where(
                Policy.organization_id == org
            )
        ).scalar()
        or 0
    )
    audit_rows = _count(db, select(func.count(AuditLog.id)).where(AuditLog.organization_id == org))

    compute = round(total_actions * _COST_PER_ACTION, 2)
    api_usage = round(total_actions * _COST_PER_ACTION * 0.5, 2)
    llm = round(total_actions * _COST_PER_LLM_ACTION, 2)
    human = round(approvals * (_HUMAN_REVIEW_MINUTES / 60) * _HUMAN_REVIEW_HOURLY, 2)
    policy_cost = round(int(policy_evals) * _COST_PER_POLICY_EVAL, 2)
    storage = round(audit_rows * _COST_PER_AUDIT_ROW_GB * 1000, 2)

    items = [
        CostItem(key="compute", label="AI Compute", amount=compute),
        CostItem(key="api", label="API Usage", amount=api_usage),
        CostItem(key="llm", label="LLM Cost", amount=llm),
        CostItem(key="human_review", label="Human Review", amount=human),
        CostItem(key="policy_eval", label="Policy Evaluation", amount=policy_cost),
        CostItem(key="storage", label="Storage", amount=storage),
    ]
    return CostAnalytics(
        items=items,
        total=round(sum(i.amount for i in items), 2),
        period_label="All time (estimated)",
    )


# --------------------------------------------------------------------------- #
# Insights (rule-based)
# --------------------------------------------------------------------------- #
def insights(db: Session, org: uuid.UUID) -> list[Insight]:
    now = datetime.now(timezone.utc)
    today = _utc_day_start(now)
    week_ago = today - timedelta(days=7)
    two_weeks_ago = today - timedelta(days=14)
    out: list[Insight] = []

    this_week_approvals = _count(
        db,
        select(func.count(Approval.id)).where(
            Approval.organization_id == org, Approval.created_at >= week_ago
        ),
    )
    last_week_approvals = _count(
        db,
        select(func.count(Approval.id)).where(
            Approval.organization_id == org,
            Approval.created_at >= two_weeks_ago,
            Approval.created_at < week_ago,
        ),
    )
    change, direction = _pct_change(this_week_approvals, last_week_approvals)
    if change is not None and abs(change) >= 1:
        verb = "increased" if direction == "up" else "decreased"
        out.append(
            Insight(
                id="approval_volume",
                title=f"Approval volume {verb} {abs(change)}% this week",
                detail=f"{this_week_approvals} approvals this week vs {last_week_approvals} last week.",
                tone="negative" if direction == "up" else "positive",
                metric=f"{abs(change)}%",
            )
        )

    # Risk movement week over week.
    avg_now = _avg_risk_between(db, org, week_ago, today)
    avg_prev = _avg_risk_between(db, org, two_weeks_ago, week_ago)
    rchange, rdir = _pct_change(avg_now, avg_prev)
    if rchange is not None and abs(rchange) >= 1:
        verb = "increased" if rdir == "up" else "decreased"
        out.append(
            Insight(
                id="risk_movement",
                title=f"Average organizational AI risk {verb} by {abs(rchange)}%",
                detail=f"Average risk is {round(avg_now)} this week vs {round(avg_prev)} last week.",
                tone="negative" if rdir == "up" else "positive",
                metric=f"{abs(rchange)}%",
            )
        )

    # Top approval-generating agent.
    top_agent = db.execute(
        select(Agent.name, func.count(Approval.id).label("c"))
        .join(Approval, Approval.requested_by_agent_id == Agent.id)
        .where(Approval.organization_id == org)
        .group_by(Agent.name)
        .order_by(func.count(Approval.id).desc())
        .limit(1)
    ).first()
    if top_agent and top_agent[1] > 0:
        out.append(
            Insight(
                id="top_approval_agent",
                title=f"{top_agent[0]} generated the most approvals",
                detail=f"{top_agent[0]} accounts for {top_agent[1]} approval request(s).",
                tone="neutral",
                metric=str(top_agent[1]),
            )
        )

    # Most-triggered policy.
    top_policy = db.execute(
        select(Policy.name, Policy.trigger_count)
        .where(Policy.organization_id == org)
        .order_by(Policy.trigger_count.desc())
        .limit(1)
    ).first()
    if top_policy and (top_policy[1] or 0) > 0:
        out.append(
            Insight(
                id="top_policy",
                title=f"Policy '{top_policy[0]}' is the most frequently triggered",
                detail=f"It has triggered {top_policy[1]} time(s).",
                tone="neutral",
                metric=str(top_policy[1]),
            )
        )

    if not out:
        out.append(
            Insight(
                id="no_signal",
                title="Not enough activity yet for trend insights",
                detail="Insights will appear as AI agents begin processing work.",
                tone="neutral",
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
_REPORT_PERIODS = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 90, "annual": 365}


def report(db: Session, org: uuid.UUID, period: str = "weekly") -> AnalyticsReport:
    now = datetime.now(timezone.utc)
    days = _REPORT_PERIODS.get(period, 7)
    start = _utc_day_start(now) - timedelta(days=days - 1)

    def cnt(model, *where) -> int:
        return _count(db, select(func.count(model.id)).where(model.organization_id == org, *where))

    actions = cnt(AgentAction, AgentAction.created_at >= start)
    allowed = cnt(
        AgentAction, AgentAction.created_at >= start, AgentAction.decision == ActionDecision.ALLOW
    )
    blocked = cnt(
        AgentAction, AgentAction.created_at >= start, AgentAction.decision == ActionDecision.BLOCK
    )
    pending = cnt(
        AgentAction,
        AgentAction.created_at >= start,
        AgentAction.decision == ActionDecision.PENDING_APPROVAL,
    )
    approvals = cnt(Approval, Approval.created_at >= start)
    fh = fleet_health(db, org)
    cost = cost_analytics(db, org)

    sections = [
        ReportSection(
            title="Activity",
            rows=[
                ReportRow(label="Total Actions", value=str(actions)),
                ReportRow(label="Allowed", value=str(allowed)),
                ReportRow(label="Blocked", value=str(blocked)),
                ReportRow(label="Pending Approval", value=str(pending)),
                ReportRow(label="Approvals Created", value=str(approvals)),
            ],
        ),
        ReportSection(
            title="Fleet",
            rows=[
                ReportRow(label="Total Agents", value=str(fh.total)),
                ReportRow(label="Healthy", value=str(fh.healthy)),
                ReportRow(label="Warning", value=str(fh.warning)),
                ReportRow(label="Offline", value=str(fh.offline)),
                ReportRow(label="Blocked", value=str(fh.blocked)),
            ],
        ),
        ReportSection(
            title="Estimated Cost (USD)",
            rows=[ReportRow(label=i.label, value=f"${i.amount:.2f}") for i in cost.items]
            + [ReportRow(label="Total", value=f"${cost.total:.2f}")],
        ),
    ]
    return AnalyticsReport(
        period=period,
        label=f"{period.capitalize()} report",
        generated_at=now,
        sections=sections,
    )


# --------------------------------------------------------------------------- #
# Overview composite
# --------------------------------------------------------------------------- #
def overview(db: Session, org: uuid.UUID) -> AnalyticsOverview:
    risk = risk_analytics(db, org)
    return AnalyticsOverview(
        generated_at=datetime.now(timezone.utc),
        kpis=kpis(db, org),
        fleet_health=fleet_health(db, org),
        risk_distribution=risk.distribution,
        activity=activity(db, org, "daily"),
        insights=insights(db, org),
    )
