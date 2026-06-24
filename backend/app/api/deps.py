"""Shared FastAPI dependencies: DB session, authentication, RBAC and context."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.enums import AgentStatus, UserRole
from app.core.security import decode_access_token
from app.models.agent import Agent
from app.models.user import User
from app.services import api_key_service, rbac_service
from app.services.agent_action_service import RequestContext

# HTTPBearer renders an "Authorize" button in Swagger where you paste a token
# (either a user JWT, or an agent API key like ``agt_live_...``).
bearer_scheme = HTTPBearer(auto_error=True)


# --------------------------------------------------------------------------- #
# User (JWT) authentication
# --------------------------------------------------------------------------- #
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the authenticated user from the bearer JWT."""
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise credentials_error
    subject = payload.get("sub")
    if not subject:
        raise credentials_error
    try:
        user_id = uuid.UUID(subject)
    except (ValueError, TypeError):
        raise credentials_error

    user = db.get(User, user_id)
    if user is None:
        raise credentials_error
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive."
        )
    return user


# --------------------------------------------------------------------------- #
# Role / permission authorization
# --------------------------------------------------------------------------- #
def require_roles(*roles: UserRole) -> Callable[[User], User]:
    """Restrict a route to the given legacy roles."""
    allowed: Iterable[UserRole] = roles

    def _checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return current_user

    return _checker


def require_permission(code: str) -> Callable[..., User]:
    """Restrict a route to users holding the given RBAC permission code."""

    def _checker(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not rbac_service.user_has_permission(db, current_user, code):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {code}",
            )
        return current_user

    return _checker


# --------------------------------------------------------------------------- #
# Agent (API key) authentication
# --------------------------------------------------------------------------- #
def get_current_agent(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Agent:
    """Resolve an agent from an ``agt_live_...`` API key."""
    agent = api_key_service.authenticate(db, credentials.credentials)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked agent API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if agent.status != AgentStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Agent is not active."
        )
    return agent


# --------------------------------------------------------------------------- #
# Combined principal for /agent-actions (agent API key OR user JWT)
# --------------------------------------------------------------------------- #
@dataclass
class ActionPrincipal:
    organization_id: uuid.UUID
    agent: Agent | None = None      # set when authenticated via agent API key
    user: User | None = None        # set when authenticated via user JWT


def get_action_principal(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> ActionPrincipal:
    """Authenticate an /agent-actions caller as either an agent or a user.

    Agent API keys carry the configured prefix; anything else is treated as a
    user JWT.
    """
    token = credentials.credentials
    if token.startswith(settings.API_KEY_PREFIX):
        agent = api_key_service.authenticate(db, token)
        if agent is None or agent.status != AgentStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid, revoked or inactive agent API key.",
            )
        return ActionPrincipal(organization_id=agent.organization_id, agent=agent)

    user = get_current_user(credentials, db)
    return ActionPrincipal(organization_id=user.organization_id, user=user)


# --------------------------------------------------------------------------- #
# Request context for the audit trail
# --------------------------------------------------------------------------- #
def get_request_context(request: Request) -> RequestContext:
    """Extract ip / user-agent / request id / trace id from the HTTP request."""
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    trace_id = request.headers.get("x-trace-id") or request_id
    return RequestContext(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=request_id,
        trace_id=trace_id,
    )
