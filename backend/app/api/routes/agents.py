"""Agent management routes (scoped to the caller's organization)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.core.enums import ActorType, AgentStatus, UserRole
from app.core.security import generate_api_key, hash_api_key
from app.models.agent import Agent
from app.models.user import User
from app.schemas.agent import (
    AgentCreate,
    AgentCreateResponse,
    AgentRead,
    AgentStatusUpdate,
)
from app.services import audit_service, notification_service

router = APIRouter(prefix="/agents", tags=["agents"])


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

    # Build the response explicitly so the plaintext key is included exactly once.
    return AgentCreateResponse(
        **AgentRead.model_validate(agent).model_dump(), api_key=api_key
    )


@router.get("", response_model=list[AgentRead])
def list_agents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Agent]:
    """List all agents in the caller's organization."""
    stmt = select(Agent).where(
        Agent.organization_id == current_user.organization_id
    ).order_by(Agent.created_at)
    return list(db.execute(stmt).scalars().all())


@router.get("/{agent_id}", response_model=AgentRead)
def get_agent(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Agent:
    """Fetch a single agent from the caller's organization."""
    agent = _get_org_agent(db, agent_id, current_user)
    return agent


@router.patch("/{agent_id}/status", response_model=AgentRead)
def update_agent_status(
    agent_id: uuid.UUID,
    payload: AgentStatusUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
) -> Agent:
    """Activate, deactivate or suspend an agent (ADMIN+ only)."""
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
