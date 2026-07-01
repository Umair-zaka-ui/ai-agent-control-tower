"""Authentication routes: register, login and current-user."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_request_context
from app.core.database import get_db
from app.core.enums import ActorType
from app.core.security import create_access_token
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, Token
from app.schemas.user import UserRead
from app.services import audit_service, auth_service
from app.services.agent_action_service import RequestContext

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> Token:
    """Bootstrap a new organization plus its first SUPER_ADMIN user (+ RBAC)."""
    if auth_service.email_exists(db, payload.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered."
        )

    user = auth_service.register_organization(
        db,
        organization_name=payload.organization_name,
        name=payload.name,
        email=payload.email,
        password=payload.password,
    )
    db.commit()

    token = create_access_token(subject=str(user.id))
    return Token(access_token=token)


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> Token:
    """Exchange email + password for a JWT access token."""
    ctx = get_request_context(request)
    user = auth_service.authenticate_user(db, payload.email, payload.password)
    if user is None:
        _audit_login_failed(db, payload.email, ctx, "Incorrect email or password.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )
    if not user.is_active:
        _audit_login_failed(db, payload.email, ctx, "Account inactive.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive."
        )

    audit_service.log_event(
        db,
        organization_id=user.organization_id,
        actor_type=ActorType.USER,
        actor_id=user.id,
        event_type="AUTH_LOGIN",
        entity_type="user",
        entity_id=user.id,
        metadata={"email": user.email},
        ip_address=ctx.ip_address,
        user_agent=ctx.user_agent,
        request_id=ctx.request_id,
        trace_id=ctx.trace_id,
    )
    db.commit()

    token = create_access_token(subject=str(user.id))
    return Token(access_token=token)


def _audit_login_failed(
    db: Session, email: str, ctx: RequestContext, reason: str
) -> None:
    """Record a failed login when the email maps to a known org (else skip)."""
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        return
    audit_service.log_event(
        db,
        organization_id=user.organization_id,
        actor_type=ActorType.USER,
        actor_id=user.id,
        event_type="AUTH_LOGIN_FAILED",
        entity_type="user",
        entity_id=user.id,
        metadata={"email": email, "reason": reason},
        ip_address=ctx.ip_address,
        user_agent=ctx.user_agent,
        request_id=ctx.request_id,
        trace_id=ctx.trace_id,
    )
    db.commit()


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)) -> User:
    """Return the currently authenticated user."""
    return current_user
