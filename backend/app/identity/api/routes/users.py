"""Identity user endpoints (SRS §9 api). Thin controllers → IdentityService."""

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
from app.identity.schemas.identity import LifecycleTransition, UserCreate, UserRead
from app.identity.services.identity_service import IdentityService
from app.models.user import User

router = APIRouter(prefix="/users", tags=["identity:users"])


@router.get("", response_model=list[UserRead])
def list_users(
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("user.view")),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[User]:
    """List users in the caller's organization (tenant-scoped)."""
    return service.list_users(current_user.organization_id, limit=limit, offset=offset)


@router.post("", response_model=UserRead, status_code=201)
def create_user(
    payload: UserCreate,
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("user.create")),
    request_id: str | None = Depends(get_request_id),
) -> User:
    """Create a human identity."""
    if payload.organization_id != current_user.organization_id:
        raise IdentityError(ErrorCode.PERMISSION_DENIED, "Cannot create users in another organization.")
    return service.create_user(payload, actor_id=current_user.id, request_id=request_id)


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: uuid.UUID,
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("user.view")),
) -> User:
    user = service.get_user(user_id)
    if user.organization_id != current_user.organization_id:
        raise IdentityError(ErrorCode.USER_NOT_FOUND, "User does not exist.")
    return user


@router.post("/{user_id}/activate", response_model=UserRead)
def activate_user(
    user_id: uuid.UUID,
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("user.create")),
    request_id: str | None = Depends(get_request_id),
) -> User:
    _assert_same_org(service, user_id, current_user)
    return service.set_user_active(user_id, active=True, actor_id=current_user.id, request_id=request_id)


@router.post("/{user_id}/suspend", response_model=UserRead)
def suspend_user(
    user_id: uuid.UUID,
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("user.create")),
    request_id: str | None = Depends(get_request_id),
) -> User:
    _assert_same_org(service, user_id, current_user)
    return service.set_user_active(user_id, active=False, actor_id=current_user.id, request_id=request_id)


@router.post("/{user_id}/status", response_model=UserRead)
def transition_user(
    user_id: uuid.UUID,
    payload: LifecycleTransition,
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("user.create")),
    request_id: str | None = Depends(get_request_id),
) -> User:
    """Move a human identity to any valid lifecycle state (SRS §8)."""
    _assert_same_org(service, user_id, current_user)
    return service.transition_user(
        user_id, payload.target_status, actor_id=current_user.id, request_id=request_id
    )


def _assert_same_org(service: IdentityService, user_id: uuid.UUID, current_user: User) -> None:
    user = service.get_user(user_id)
    if user.organization_id != current_user.organization_id:
        raise IdentityError(ErrorCode.USER_NOT_FOUND, "User does not exist.")
