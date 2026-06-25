"""Agent management routes (scoped to the caller's organization)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy import String, asc, cast, desc, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.core.enums import (
    ActionDecision,
    ActorType,
    AgentStatus,
    ApprovalDecision,
    RiskLevel,
    UserRole,
)
from app.core.security import generate_api_key, hash_api_key
from app.models.agent import Agent
from app.models.agent_action import AgentAction
from app.models.approval import Approval
from app.models.user import User
from app.schemas.agent import (
    AgentCreate,
    AgentCreateResponse,
    AgentListResponse,
    AgentRead,
    AgentStats,
    AgentStatusUpdate,
    AgentUpdate,
)
from app.services import audit_service, notification_service

router = APIRouter(prefix="/agents", tags=["agents"])

# Columns the agents table is allowed to sort by.
_SORTABLE = {
    "name": Agent.name,
    "agent_type": Agent.agent_type,
    "status": Agent.status,
    "risk_level": Agent.risk_level,
    "version": Agent.version,
    "created_at": Agent.created_at,
    "updated_at": Agent.updated_at,
}


@router.post("", response_model=AgentCreateResponse, status_code=status.HTTP_201_CREATED)
def create_agent(
    payload: AgentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
) -> AgentCreateResponse:
    """Register a new agent and return its one-time plaintext API key."""
    api_key = generate_api_key()
    agent = Agent(
        organization_id=current_user.organization_id,
        name=payload.name,
        description=payload.description,
        agent_type=payload.agent_type,
        api_key_hash=hash_api_key(api_key),
        owner=payload.owner,
        department=payload.department,
        version=payload.version,
        capabilities=payload.capabilities,
        default_risk_score=payload.default_risk_score,
        max_allowed_risk=payload.max_allowed_risk,
        human_approval_required=payload.human_approval_required,
        auto_suspend_threshold=payload.auto_suspend_threshold,
        risk_level=payload.risk_level.value,
    )
    db.add(agent)
    db.flush()

    audit_service.log_event(
        db,
        organization_id=current_user.organization_id,
        actor_type=ActorType.USER,
        actor_id=current_user.id,
        event_type="AGENT_CREATED",
        entity_type="agent",
        entity_id=agent.id,
        metadata={"name": agent.name, "agent_type": agent.agent_type},
    )
    db.commit()

    return AgentCreateResponse(
        **AgentRead.model_validate(agent).model_dump(), api_key=api_key
    )


@router.get("", response_model=AgentListResponse)
def list_agents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    search: str | None = Query(default=None),
    status_filter: AgentStatus | None = Query(default=None, alias="status"),
    agent_type: str | None = Query(default=None),
    risk_level: RiskLevel | None = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> AgentListResponse:
    """List agents with server-side search, filtering, sorting and pagination."""
    org = current_user.organization_id
    conditions = [Agent.organization_id == org]

    if search:
        like = f"%{search.strip()}%"
        conditions.append(
            or_(
                Agent.name.ilike(like),
                Agent.agent_type.ilike(like),
                Agent.owner.ilike(like),
                cast(Agent.id, String).ilike(like),
            )
        )
    if status_filter is not None:
        conditions.append(Agent.status == status_filter)
    if agent_type is not None:
        conditions.append(Agent.agent_type == agent_type)
    if risk_level is not None:
        conditions.append(Agent.risk_level == risk_level.value)

    total = db.execute(
        select(func.count(Agent.id)).where(*conditions)
    ).scalar_one() or 0

    sort_col = _SORTABLE.get(sort_by, Agent.created_at)
    order = asc(sort_col) if sort_dir == "asc" else desc(sort_col)
    stmt = (
        select(Agent)
        .where(*conditions)
        .order_by(order)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list(db.execute(stmt).scalars().all())

    return AgentListResponse(
        items=[AgentRead.model_validate(a) for a in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{agent_id}", response_model=AgentRead)
def get_agent(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Agent:
    """Fetch a single agent from the caller's organization."""
    return _get_org_agent(db, agent_id, current_user)


@router.put("/{agent_id}", response_model=AgentRead)
def update_agent(
    agent_id: uuid.UUID,
    payload: AgentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
) -> Agent:
    """Update an agent's metadata / configuration (ADMIN+ only)."""
    agent = _get_org_agent(db, agent_id, current_user)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if field in {"risk_level", "status"} and value is not None:
            value = value.value if hasattr(value, "value") else value
        setattr(agent, field, value)
    db.flush()

    audit_service.log_event(
        db,
        organization_id=current_user.organization_id,
        actor_type=ActorType.USER,
        actor_id=current_user.id,
        event_type="AGENT_UPDATED",
        entity_type="agent",
        entity_id=agent.id,
        metadata={"fields": sorted(changes.keys())},
    )
    db.commit()
    return agent


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_agent(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
) -> Response:
    """Permanently delete an agent and its dependent records (ADMIN+ only)."""
    agent = _get_org_agent(db, agent_id, current_user)
    audit_service.log_event(
        db,
        organization_id=current_user.organization_id,
        actor_type=ActorType.USER,
        actor_id=current_user.id,
        event_type="AGENT_DELETED",
        entity_type="agent",
        entity_id=agent.id,
        metadata={"name": agent.name},
    )
    db.delete(agent)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{agent_id}/stats", response_model=AgentStats)
def agent_stats(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentStats:
    """Per-agent operational statistics for the details Overview."""
    agent = _get_org_agent(db, agent_id, current_user)
    org = agent.organization_id
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    def count(*conditions) -> int:
        base = [AgentAction.organization_id == org, AgentAction.agent_id == agent.id]
        return db.execute(
            select(func.count(AgentAction.id)).where(*base, *conditions)
        ).scalar_one() or 0

    total_actions = count()
    blocked = count(AgentAction.decision == ActionDecision.BLOCK)
    allowed = count(AgentAction.decision == ActionDecision.ALLOW)
    escalated = count(AgentAction.decision == ActionDecision.PENDING_APPROVAL)
    actions_today = count(AgentAction.created_at >= today_start)

    avg_risk = db.execute(
        select(func.avg(AgentAction.risk_score)).where(
            AgentAction.organization_id == org, AgentAction.agent_id == agent.id
        )
    ).scalar()

    pending_approvals = db.execute(
        select(func.count(Approval.id)).where(
            Approval.organization_id == org,
            Approval.requested_by_agent_id == agent.id,
            Approval.decision == ApprovalDecision.PENDING,
        )
    ).scalar_one() or 0

    success_rate = (allowed / total_actions) if total_actions else 0.0

    return AgentStats(
        actions_today=actions_today,
        total_actions=total_actions,
        blocked_actions=blocked,
        pending_approvals=pending_approvals,
        policies_triggered=escalated,
        average_risk=round(float(avg_risk or 0)),
        success_rate=round(success_rate, 4),
    )


@router.patch("/{agent_id}/status", response_model=AgentRead)
def update_agent_status(
    agent_id: uuid.UUID,
    payload: AgentStatusUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
) -> Agent:
    """Activate, deactivate, suspend, archive or block an agent (ADMIN+ only)."""
    agent = _get_org_agent(db, agent_id, current_user)
    previous = agent.status
    agent.status = payload.status
    db.flush()

    audit_service.log_event(
        db,
        organization_id=current_user.organization_id,
        actor_type=ActorType.USER,
        actor_id=current_user.id,
        event_type="AGENT_STATUS_CHANGED",
        entity_type="agent",
        entity_id=agent.id,
        metadata={"from": previous.value, "to": agent.status.value},
    )

    agent_name = agent.name
    notify = payload.status == AgentStatus.SUSPENDED and previous != AgentStatus.SUSPENDED
    recipients = _admin_emails(db, current_user.organization_id) if notify else []
    db.commit()

    if notify and recipients:
        background_tasks.add_task(
            notification_service.notify_agent_suspended, recipients, agent_name=agent_name
        )
    return agent


def _admin_emails(db: Session, organization_id: uuid.UUID) -> list[str]:
    stmt = select(User.email).where(
        User.organization_id == organization_id,
        User.is_active.is_(True),
        User.role.in_([UserRole.SUPER_ADMIN, UserRole.ADMIN]),
    )
    return [e for (e,) in db.execute(stmt).all()]


def _get_org_agent(db: Session, agent_id: uuid.UUID, current_user: User) -> Agent:
    """Load an agent ensuring it belongs to the caller's organization."""
    agent = db.get(Agent, agent_id)
    if agent is None or agent.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found."
        )
    return agent
