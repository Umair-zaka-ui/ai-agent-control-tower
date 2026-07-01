"""Identity department endpoints (SRS §9 api)."""

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
from app.identity.models.department import Department
from app.identity.schemas.identity import DepartmentCreate, DepartmentRead
from app.identity.services.identity_service import IdentityService
from app.models.user import User

router = APIRouter(prefix="/departments", tags=["identity:departments"])


@router.get("", response_model=list[DepartmentRead])
def list_departments(
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("user.view")),
) -> list[Department]:
    return service.list_departments(current_user.organization_id)


@router.post("", response_model=DepartmentRead, status_code=201)
def create_department(
    payload: DepartmentCreate,
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("user.create")),
    request_id: str | None = Depends(get_request_id),
) -> Department:
    if payload.organization_id != current_user.organization_id:
        raise IdentityError(
            ErrorCode.PERMISSION_DENIED, "Cannot create departments in another organization."
        )
    return service.create_department(payload, actor_id=current_user.id, request_id=request_id)


@router.get("/{department_id}", response_model=DepartmentRead)
def get_department(
    department_id: uuid.UUID,
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("user.view")),
) -> Department:
    dept = service.get_department(department_id)
    if dept.organization_id != current_user.organization_id:
        raise IdentityError(ErrorCode.DEPARTMENT_NOT_FOUND, "Department does not exist.")
    return dept
