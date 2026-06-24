"""Agent API key routes - issue, list and revoke keys."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.enums import ActorType
from app.models.agent import Agent
from app.models.api_key import AgentApiKey
from app.models.user import User
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreateResponse, ApiKeyRead
from app.services import api_key_service, audit_service

router = APIRouter(tags=["api-keys"])


def _get_org_agent(db: Session, agent_id: uuid.UUID, user: User) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None or agent.organization_id != user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return agent


@router.post(
    "/agents/{agent_id}/generate-api-key",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_api_key(
    agent_id: uuid.UUID,
    payload: ApiKeyCreate | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("apikey.create")),
) -> ApiKeyCreateResponse:
    """Issue a new API key for an agent. The plaintext key is shown once."""
    agent = _get_org_agent(db, agent_id, current_user)
    expires_at = payload.expires_at if payload else None
    record, raw_key = api_key_service.issue_api_key(db, agent, expires_at=expires_at)

    audit_service.log_event(
        db,
        organization_id=current_user.organization_id,
        actor_type=ActorType.USER,
        actor_id=current_user.id,
        event_type="API_KEY_ISSUED",
        entity_type="agent_api_key",
        entity_id=record.id,
        metadata={"agent_id": str(agent.id), "key_prefix": record.key_prefix},
    )
    db.commit()
    return ApiKeyCreateResponse(
        id=record.id, agent_id=agent.id, key_prefix=record.key_prefix, api_key=raw_key
    )


@router.get("/agents/{agent_id}/api-keys", response_model=list[ApiKeyRead])
def list_api_keys(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("agent.view")),
) -> list[AgentApiKey]:
    """List an agent's API keys (hashes are never returned)."""
    agent = _get_org_agent(db, agent_id, current_user)
    return api_key_service.list_keys(db, agent.id)


@router.post("/api-keys/{key_id}/revoke", response_model=ApiKeyRead)
def revoke_api_key(
    key_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("apikey.revoke")),
) -> AgentApiKey:
    """Revoke an API key so it can no longer authenticate."""
    record = db.get(AgentApiKey, key_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")
    agent = db.get(Agent, record.agent_id)
    if agent is None or agent.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")

    api_key_service.revoke_key(db, record)
    audit_service.log_event(
        db,
        organization_id=current_user.organization_id,
        actor_type=ActorType.USER,
        actor_id=current_user.id,
        event_type="API_KEY_REVOKED",
        entity_type="agent_api_key",
        entity_id=record.id,
        metadata={"agent_id": str(record.agent_id), "key_prefix": record.key_prefix},
    )
    db.commit()
    return record
