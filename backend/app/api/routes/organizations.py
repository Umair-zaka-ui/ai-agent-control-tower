"""Organization routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.core.enums import ActorType, UserRole
from app.models.organization import Organization
from app.models.user import User
from app.schemas.organization import OrganizationCreate, OrganizationRead
from app.services import audit_service

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrganizationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.SUPER_ADMIN)),
) -> Organization:
    """Create a new organization (SUPER_ADMIN only)."""
    organization = Organization(name=payload.name)
    db.add(organization)
    db.flush()

    audit_service.log_event(
        db,
        organization_id=organization.id,
        actor_type=ActorType.USER,
        actor_id=current_user.id,
        event_type="ORGANIZATION_CREATED",
        entity_type="organization",
        entity_id=organization.id,
        metadata={"name": organization.name},
    )
    db.commit()
    return organization


@router.get("/{organization_id}", response_model=OrganizationRead)
def get_organization(
    organization_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Organization:
    """Fetch a single organization. Users may only read their own org."""
    if organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only access your own organization.",
        )
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found."
        )
    return organization
