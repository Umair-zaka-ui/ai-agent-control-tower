"""Agent action routes - submit an action and inspect past actions."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.agent import Agent
from app.models.agent_action import AgentAction
from app.models.user import User
from app.schemas.agent_action import (
    AgentActionCreate,
    AgentActionDecisionResponse,
    AgentActionRead,
)
from app.services import agent_action_service

router = APIRouter(prefix="/agent-actions", tags=["agent-actions"])


@router.post("", response_model=AgentActionDecisionResponse, status_code=status.HTTP_201_CREATED)
def submit_agent_action(
    payload: AgentActionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentActionDecisionResponse:
    """Submit an agent action through the governance pipeline.

    Runs permission check -> risk scoring -> decision, persists the action and
    an audit log, and (when required) enqueues a human approval request.
    """
    agent = db.get(Agent, payload.agent_id)
    if agent is None or agent.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found."
        )

    action, approval = agent_action_service.process_agent_action(
        db,
        agent=agent,
        resource=payload.resource,
        action=payload.action,
        input_payload=payload.input_payload,
    )
    db.commit()

    return AgentActionDecisionResponse(
        agent_action_id=action.id,
        decision=action.decision,
        risk_score=action.risk_score,
        decision_reason=action.decision_reason,
        status=action.status,
        approval_id=approval.id if approval else None,
    )


@router.get("", response_model=list[AgentActionRead])
def list_agent_actions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    agent_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[AgentAction]:
    """List agent actions in the caller's organization (newest first)."""
    stmt = select(AgentAction).where(
        AgentAction.organization_id == current_user.organization_id
    )
    if agent_id is not None:
        stmt = stmt.where(AgentAction.agent_id == agent_id)
    stmt = stmt.order_by(AgentAction.created_at.desc()).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())


@router.get("/{agent_action_id}", response_model=AgentActionRead)
def get_agent_action(
    agent_action_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AgentAction:
    """Fetch a single agent action."""
    action = db.get(AgentAction, agent_action_id)
    if action is None or action.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent action not found."
        )
    return action
