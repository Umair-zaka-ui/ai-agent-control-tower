"""Dashboard routes - aggregated metrics and feeds for the future frontend."""

from __future__ import annotations

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
from app.schemas.dashboard import DashboardSummary
from app.schemas.approval import ApprovalRead

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# High-risk feed threshold.
HIGH_RISK_THRESHOLD = 70


def _count(db: Session, stmt) -> int:
    return db.execute(stmt).scalar_one() or 0


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("dashboard.view")),
) -> DashboardSummary:
    """Headline counts for the organization."""
    org = current_user.organization_id
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
    )


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
