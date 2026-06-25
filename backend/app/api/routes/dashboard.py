"""Dashboard routes - aggregated metrics and feeds for the future frontend."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.enums import (
    ActionDecision,
    ActionStatus,
    AgentStatus,
    ApprovalDecision,
)
from app.models.agent import Agent
from app.models.agent_action import AgentAction
from app.models.approval import Approval
from app.models.policy import Policy
from app.models.user import User
from app.schemas.agent_action import AgentActionRead
from app.schemas.dashboard import (
    ActivityPoint,
    DashboardSummary,
    RiskTrendPoint,
)
from app.schemas.approval import ApprovalRead

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# High-risk feed threshold.
HIGH_RISK_THRESHOLD = 70


def _count(db: Session, stmt) -> int:
    return db.execute(stmt).scalar_one() or 0


def _utc_day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.view")),
) -> DashboardSummary:
    """Headline counts for the organization."""
    org = current_user.organization_id
    today_start = _utc_day_start(datetime.now(timezone.utc))
    return DashboardSummary(
        agents=_count(db, select(func.count(Agent.id)).where(Agent.organization_id == org)),
        active_agents=_count(
            db,
            select(func.count(Agent.id)).where(
                Agent.organization_id == org, Agent.status == AgentStatus.ACTIVE
            ),
        ),
        pending_approvals=_count(
            db,
            select(func.count(Approval.id)).where(
                Approval.organization_id == org,
                Approval.decision == ApprovalDecision.PENDING,
            ),
        ),
        blocked_actions=_count(
            db,
            select(func.count(AgentAction.id)).where(
                AgentAction.organization_id == org,
                AgentAction.decision == ActionDecision.BLOCK,
            ),
        ),
        policies=_count(db, select(func.count(Policy.id)).where(Policy.organization_id == org)),
        total_actions=_count(
            db, select(func.count(AgentAction.id)).where(AgentAction.organization_id == org)
        ),
        today_actions=_count(
            db,
            select(func.count(AgentAction.id)).where(
                AgentAction.organization_id == org,
                AgentAction.created_at >= today_start,
            ),
        ),
    )


@router.get("/activity", response_model=list[ActivityPoint])
def agent_activity(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.view")),
    days: int = Query(default=7, ge=1, le=31),
) -> list[ActivityPoint]:
    """Daily agent-action counts for the last N days (default 7), oldest first.

    Days with no activity are returned as zero so the chart is always a
    continuous series.
    """
    org = current_user.organization_id
    today = _utc_day_start(datetime.now(timezone.utc))
    start = today - timedelta(days=days - 1)

    rows = db.execute(
        select(
            func.date(func.timezone("UTC", AgentAction.created_at)).label("day"),
            func.count(AgentAction.id),
        )
        .where(AgentAction.organization_id == org, AgentAction.created_at >= start)
        .group_by(func.date(func.timezone("UTC", AgentAction.created_at)))
    ).all()
    counts = {str(day): total for day, total in rows}

    series: list[ActivityPoint] = []
    for offset in range(days):
        day = (start + timedelta(days=offset)).date()
        series.append(
            ActivityPoint(date=day.strftime("%a"), actions=counts.get(str(day), 0))
        )
    return series


@router.get("/risk-trend", response_model=list[RiskTrendPoint])
def risk_trend(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.view")),
    days: int = Query(default=30, ge=1, le=90),
) -> list[RiskTrendPoint]:
    """Average organizational risk score per day for the last N days (default 30).

    Days with no actions report a risk score of 0.
    """
    org = current_user.organization_id
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


@router.get("/recent-actions", response_model=list[AgentActionRead])
def recent_actions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.view")),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[AgentAction]:
    """Most recent agent actions across the organization."""
    stmt = (
        select(AgentAction)
        .where(AgentAction.organization_id == current_user.organization_id)
        .order_by(AgentAction.created_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


@router.get("/high-risk-actions", response_model=list[AgentActionRead])
def high_risk_actions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.view")),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[AgentAction]:
    """Recent actions at or above the high-risk threshold."""
    stmt = (
        select(AgentAction)
        .where(
            AgentAction.organization_id == current_user.organization_id,
            AgentAction.risk_score >= HIGH_RISK_THRESHOLD,
        )
        .order_by(AgentAction.risk_score.desc(), AgentAction.created_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


@router.get("/pending-approvals", response_model=list[ApprovalRead])
def pending_approvals(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.view")),
) -> list[Approval]:
    """Pending approvals ordered by priority then age."""
    stmt = (
        select(Approval)
        .where(
            Approval.organization_id == current_user.organization_id,
            Approval.decision == ApprovalDecision.PENDING,
        )
        .order_by(Approval.created_at)
    )
    return list(db.execute(stmt).scalars().all())
