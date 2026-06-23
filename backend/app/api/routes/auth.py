"""Authentication routes: register, login and current-user."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.enums import ActorType, UserRole
from app.core.security import create_access_token, hash_password, verify_password
from app.models.organization import Organization
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, Token
from app.schemas.user import UserRead
from app.services import audit_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> Token:
    """Bootstrap a new organization plus its first SUPER_ADMIN user."""
    existing = db.execute(
        select(User).where(User.email == payload.email)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered."
        )

    organization = Organization(name=payload.organization_name)
    db.add(organization)
    db.flush()

    user = User(
        organization_id=organization.id,
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=UserRole.SUPER_ADMIN,
        is_active=True,
    )
    db.add(user)
    db.flush()

    audit_service.log_event(
        db,
        organization_id=organization.id,
        actor_type=ActorType.USER,
        actor_id=user.id,
        event_type="USER_REGISTERED",
        entity_type="user",
        entity_id=user.id,
        metadata={"email": user.email, "role": user.role.value},
    )

    db.commit()

    token = create_access_token(subject=str(user.id))
    return Token(access_token=token)


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> Token:
    """Exchange email + password for a JWT access token."""
    user = db.execute(
        select(User).where(User.email == payload.email)
    ).scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive."
        )

    token = create_access_token(subject=str(user.id))
    return Token(access_token=token)


@router.get("/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)) -> User:
    """Return the currently authenticated user."""
    return current_user
