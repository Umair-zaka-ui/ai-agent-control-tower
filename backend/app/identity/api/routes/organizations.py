"""Identity organization endpoints (SRS §9 api)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.identity.api.deps import get_current_user, get_identity_service, require_permission
from app.identity.errors import ErrorCode, IdentityError
from app.identity.schemas.identity import OrganizationRead
from app.identity.services.identity_service import IdentityService
from app.models.organization import Organization
from app.models.user import User

router = APIRouter(prefix="/organizations", tags=["identity:organizations"])


@router.get("", response_model=list[OrganizationRead])
def list_organizations(
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("user.view")),
) -> list[Organization]:
    """The caller's own organization (tenant isolation)."""
    org = service.organizations.get(current_user.organization_id)
    return [org] if org is not None else []


@router.get("/{organization_id}", response_model=OrganizationRead)
def get_organization(
    organization_id: uuid.UUID,
    service: IdentityService = Depends(get_identity_service),
    current_user: User = Depends(require_permission("user.view")),
) -> Organization:
    if organization_id != current_user.organization_id:
        raise IdentityError(ErrorCode.ORGANIZATION_NOT_FOUND, "Organization does not exist.")
    org = service.organizations.get(organization_id)
    if org is None:
        raise IdentityError(ErrorCode.ORGANIZATION_NOT_FOUND, "Organization does not exist.")
    return org
