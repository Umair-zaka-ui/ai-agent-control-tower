"""Service account endpoints (SRS §7). Backend automation identities."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.identity.api.deps import (
    get_current_user,
    get_identity_service,
    get_request_id,
    require_permission,
)
from app.identity.errors import ErrorCode, IdentityError
from app.identity.models.enums import IdentityType
from app.identity.schemas.identity import (
    LifecycleTransition,
    ServiceAccountCreate,
    ServiceAccountCreated,
    ServiceAccountRead,
)
from app.identity.services.identity_service import IdentityService
from app.models.user import User

router = APIRouter(prefix="/service-accounts", tags=["identity:service-accounts"])


@router.get("", response_model=list[ServiceAccountRead])
def list_service_accounts(
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("user.view")),
):
    return service.list_service_accounts(current_user.organization_id)


@router.post("", response_model=ServiceAccountCreated, status_code=201)
def create_service_account(
    payload: ServiceAccountCreate,
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("user.create")),
    request_id: str | None = Depends(get_request_id),
) -> ServiceAccountCreated:
    if payload.organization_id != current_user.organization_id:
        raise IdentityError(
            ErrorCode.PERMISSION_DENIED, "Cannot create service accounts in another organization."
        )
    account, secret = service.create_service_account(
        payload, actor_id=current_user.id, request_id=request_id
    )
    read = ServiceAccountRead.model_validate(account)
    return ServiceAccountCreated(**read.model_dump(), client_secret=secret)


@router.get("/{account_id}", response_model=ServiceAccountRead)
def get_service_account(
    account_id: uuid.UUID,
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("user.view")),
):
    account = service.get_service_account(account_id)
    if account.organization_id != current_user.organization_id:
        raise IdentityError(ErrorCode.SERVICE_ACCOUNT_NOT_FOUND, "Service account does not exist.")
    return account


@router.post("/{account_id}/status", response_model=ServiceAccountRead)
def transition_service_account(
    account_id: uuid.UUID,
    payload: LifecycleTransition,
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("user.create")),
    request_id: str | None = Depends(get_request_id),
):
    account = service.get_service_account(account_id)
    if account.organization_id != current_user.organization_id:
        raise IdentityError(ErrorCode.SERVICE_ACCOUNT_NOT_FOUND, "Service account does not exist.")
    return service.transition_status(
        account,
        payload.target_status,
        organization_id=current_user.organization_id,
        actor_id=current_user.id,
        actor_type=IdentityType.SERVICE_ACCOUNT,
        target_type="service_account",
        request_id=request_id,
    )
