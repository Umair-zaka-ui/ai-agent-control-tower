"""Agent action routes - submit an action and inspect past actions.

Authentication accepts EITHER an agent API key (``agt_live_...``) or a user JWT.
With an API key the acting agent is taken from the key; with a JWT the agent is
taken from the request body and must belong to the user's organization.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    ActionPrincipal,
    get_action_principal,
    get_current_user,
    get_request_context,
)
from app.core.database import get_db
from app.core.enums import ActionDecision, UserRole
from app.models.agent import Agent
from app.models.agent_action import AgentAction
from app.models.user import User
from app.schemas.agent_action import (
    AgentActionCreate,
    AgentActionDecisionResponse,
    AgentActionRead,
)
from app.services import agent_action_service, notification_service

router = APIRouter(prefix="/agent-actions", tags=["agent-actions"])


def _reviewer_emails(db: Session, organization_id: uuid.UUID) -> list[str]:
    stmt = select(User.email).where(
        User.organization_id == organization_id,
        User.is_active.is_(True),
        User.role.in_([UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.REVIEWER]),
    )
    return [e for (e,) in db.execute(stmt).all()]


@router.post("", response_model=AgentActionDecisionResponse, status_code=status.HTTP_201_CREATED)
def submit_agent_action(
    payload: AgentActionCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    principal: ActionPrincipal = Depends(get_action_principal),
) -> AgentActionDecisionResponse:
    """Submit an agent action through the full governance pipeline."""
    # Resolve the acting agent depending on how the caller authenticated.
    if principal.agent is not None:
        agent = principal.agent
    else:
        agent = db.get(Agent, payload.agent_id)
        if agent is None or agent.organization_id != principal.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found."
            )

    context = get_request_context(request)
    if principal.user is not None:
        context.submitted_by_user_id = str(principal.user.id)

    result = agent_action_service.process_agent_action(
        db,
        agent=agent,
        resource=payload.resource,
        action=payload.action,
        input_payload=payload.input_payload,
        context=context,
    )

    # Gather notification recipients before commit (still in session scope).
    if result.approval is not None:
        recipients = _reviewer_emails(db, agent.organization_id)
        agent_name = agent.name
    else:
        recipients = []
        agent_name = agent.name

    db.commit()

    # Fire-and-forget email once the transaction is safely committed.
    if result.approval is not None and recipients:
        background_tasks.add_task(
            notification_service.notify_approval_requested,
            recipients,
            agent_name=agent_name,
            resource=payload.resource,
            action=payload.action,
            risk_score=result.action.risk_score,
        )

    return AgentActionDecisionResponse(
        agent_action_id=result.action.id,
        decision=result.action.decision,
        risk_score=result.action.risk_score,
        decision_reason=result.action.decision_reason,
        status=result.action.status,
        approval_id=result.approval.id if result.approval else None,
        matched_policy=result.decision.matched_policy_name,
    )


@router.get("", response_model=list[AgentActionRead])
def list_agent_actions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    agent_id: uuid.UUID | None = Query(default=None),
    decision: ActionDecision | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[AgentAction]:
    """List agent actions in the caller's organization (newest first)."""
    stmt = select(AgentAction).where(
        AgentAction.organization_id == current_user.organization_id
    )
    if agent_id is not None:
        stmt = stmt.where(AgentAction.agent_id == agent_id)
    if decision is not None:
        stmt = stmt.where(AgentAction.decision == decision)
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
