"""AI agent identity endpoints (SRS §7). Identity of an agent, not the agent."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.identity.api.deps import (
    get_current_user,
    get_identity_service,
    get_request_id,
    require_permission,
)
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.enums import IdentityType
from app.identity.schemas.identity import (
    AgentIdentityCreate,
    AgentIdentityRead,
    LifecycleTransition,
)
from app.identity.services.identity_service import IdentityService
from app.models.agent import Agent
from app.models.user import User

router = APIRouter(prefix="/agent-identities", tags=["identity:agent-identities"])


def _assert_agent_in_org(service: IdentityService, agent_id: uuid.UUID, current_user: User) -> None:
    agent = service.db.get(Agent, agent_id)
    if agent is None or agent.organization_id != current_user.organization_id:
        raise IdentityError(ErrorCode.IDENTITY_NOT_FOUND, "Agent does not exist.")


@router.get("", response_model=list[AgentIdentityRead])
def list_agent_identities(
    agent_id: uuid.UUID = Query(...),
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("agent.view")),
):
    _assert_agent_in_org(service, agent_id, current_user)
    return service.list_agent_identities(agent_id)


@router.post("", response_model=AgentIdentityRead, status_code=201)
def create_agent_identity(
    payload: AgentIdentityCreate,
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("agent.create")),
    request_id: str | None = Depends(get_request_id),
):
    return service.create_agent_identity(
        payload,
        organization_id=current_user.organization_id,
        actor_id=current_user.id,
        request_id=request_id,
    )


@router.get("/{identity_id}", response_model=AgentIdentityRead)
def get_agent_identity(
    identity_id: uuid.UUID,
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("agent.view")),
):
    identity = service.get_agent_identity(identity_id)
    _assert_agent_in_org(service, identity.agent_id, current_user)
    return identity


@router.post("/{identity_id}/status", response_model=AgentIdentityRead)
def transition_agent_identity(
    identity_id: uuid.UUID,
    payload: LifecycleTransition,
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("agent.create")),
    request_id: str | None = Depends(get_request_id),
):
    identity = service.get_agent_identity(identity_id)
    _assert_agent_in_org(service, identity.agent_id, current_user)
    return service.transition_status(
        identity,
        payload.target_status,
        organization_id=current_user.organization_id,
        actor_id=current_user.id,
        actor_type=IdentityType.AI_AGENT,
        target_type="agent_identity",
        request_id=request_id,
    )
