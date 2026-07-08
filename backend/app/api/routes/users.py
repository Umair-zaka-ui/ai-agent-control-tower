"""User management routes (scoped to the caller's organization)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.core.enums import ActorType, UserRole
from app.identity.security.passwords import hash_user_password
from app.models.user import User
from app.schemas.user import UserCreate, UserRead
from app.services import audit_service

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
) -> User:
    """Create a user inside the caller's organization (ADMIN+ only)."""
    existing = db.execute(
        select(User).where(User.email == payload.email)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered."
        )

    user = User(
        organization_id=current_user.organization_id,
        name=payload.name,
        email=payload.email,
        password_hash=hash_user_password(
            payload.password, email=payload.email, username=payload.name
        ),
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    db.flush()

    audit_service.log_event(
        db,
        organization_id=current_user.organization_id,
        actor_type=ActorType.USER,
        actor_id=current_user.id,
        event_type="USER_CREATED",
        entity_type="user",
        entity_id=user.id,
        metadata={"email": user.email, "role": user.role.value},
    )
    db.commit()
    return user


@router.get("", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[User]:
    """List all users in the caller's organization."""
    stmt = select(User).where(
        User.organization_id == current_user.organization_id
    ).order_by(User.created_at)
    return list(db.execute(stmt).scalars().all())


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Fetch a single user from the caller's organization."""
    user = db.get(User, user_id)
    if user is None or user.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )
    return user
