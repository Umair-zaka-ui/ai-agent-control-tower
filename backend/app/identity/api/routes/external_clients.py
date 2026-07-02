"""External client endpoints (SRS §7). Power BI, Zapier, Salesforce, Fabric…"""

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
    ExternalClientCreate,
    ExternalClientCreated,
    ExternalClientRead,
    LifecycleTransition,
)
from app.identity.services.identity_service import IdentityService
from app.models.user import User

router = APIRouter(prefix="/external-clients", tags=["identity:external-clients"])


@router.get("", response_model=list[ExternalClientRead])
def list_external_clients(
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("user.view")),
):
    return service.list_external_clients(current_user.organization_id)


@router.post("", response_model=ExternalClientCreated, status_code=201)
def create_external_client(
    payload: ExternalClientCreate,
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("user.create")),
    request_id: str | None = Depends(get_request_id),
) -> ExternalClientCreated:
    if payload.organization_id != current_user.organization_id:
        raise IdentityError(
            ErrorCode.PERMISSION_DENIED, "Cannot register clients in another organization."
        )
    client, secret = service.create_external_client(
        payload, actor_id=current_user.id, request_id=request_id
    )
    read = ExternalClientRead.model_validate(client)
    return ExternalClientCreated(**read.model_dump(), client_secret=secret)


@router.get("/{client_id}", response_model=ExternalClientRead)
def get_external_client(
    client_id: uuid.UUID,
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("user.view")),
):
    client = service.get_external_client(client_id)
    if client.organization_id != current_user.organization_id:
        raise IdentityError(ErrorCode.EXTERNAL_CLIENT_NOT_FOUND, "External client does not exist.")
    return client


@router.post("/{client_id}/status", response_model=ExternalClientRead)
def transition_external_client(
    client_id: uuid.UUID,
    payload: LifecycleTransition,
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("user.create")),
    request_id: str | None = Depends(get_request_id),
):
    client = service.get_external_client(client_id)
    if client.organization_id != current_user.organization_id:
        raise IdentityError(ErrorCode.EXTERNAL_CLIENT_NOT_FOUND, "External client does not exist.")
    return service.transition_status(
        client,
        payload.target_status,
        organization_id=current_user.organization_id,
        actor_id=current_user.id,
        actor_type=IdentityType.EXTERNAL_CLIENT,
        target_type="external_client",
        request_id=request_id,
    )
