"""RBAC routes - inspect roles/permissions and assign roles to users."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.database import get_db
from app.core.enums import ActorType
from app.models.rbac import RbacPermission, Role, UserRole as UserRoleLink
from app.models.user import User
from app.schemas.rbac import (
    AssignRoleRequest,
    MyPermissionsResponse,
    RbacPermissionRead,
    RoleWithPermissions,
)
from app.services import audit_service, rbac_service

router = APIRouter(prefix="/rbac", tags=["rbac"])


@router.get("/permissions", response_model=list[RbacPermissionRead])
def list_permissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RbacPermission]:
    """List the full RBAC permission catalog."""
    return list(db.execute(select(RbacPermission).order_by(RbacPermission.code)).scalars().all())


@router.get("/roles", response_model=list[RoleWithPermissions])
def list_roles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RoleWithPermissions]:
    """List roles available to the caller's organization (incl. system roles)."""
    stmt = select(Role).where(
        or_(Role.organization_id == current_user.organization_id, Role.organization_id.is_(None))
    ).order_by(Role.name)
    roles = db.execute(stmt).scalars().all()
    return [
        RoleWithPermissions(
            id=r.id,
            organization_id=r.organization_id,
            name=r.name,
            description=r.description,
            is_system=r.is_system,
            created_at=r.created_at,
            updated_at=r.updated_at,
            permissions=sorted(p.code for p in r.permissions),
        )
        for r in roles
    ]


@router.get("/me", response_model=MyPermissionsResponse)
def my_permissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MyPermissionsResponse:
    """Return the caller's effective permissions."""
    perms = rbac_service.get_user_permissions(db, current_user)
    return MyPermissionsResponse(role=current_user.role.value, permissions=sorted(perms))


@router.post("/users/{user_id}/roles", response_model=MyPermissionsResponse)
def assign_role(
    user_id: uuid.UUID,
    payload: AssignRoleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("rbac.manage")),
) -> MyPermissionsResponse:
    """Assign a role to a user within the caller's organization."""
    target = db.get(User, user_id)
    if target is None or target.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    role = db.get(Role, payload.role_id)
    if role is None or (
        role.organization_id is not None
        and role.organization_id != current_user.organization_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")

    existing = db.execute(
        select(UserRoleLink).where(
            UserRoleLink.user_id == target.id, UserRoleLink.role_id == role.id
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(UserRoleLink(user_id=target.id, role_id=role.id))
        db.flush()

    audit_service.log_event(
        db,
        organization_id=current_user.organization_id,
        actor_type=ActorType.USER,
        actor_id=current_user.id,
        event_type="ROLE_ASSIGNED",
        entity_type="user",
        entity_id=target.id,
        metadata={"role": role.name, "role_id": str(role.id)},
    )
    db.commit()

    perms = rbac_service.get_user_permissions(db, target)
    return MyPermissionsResponse(role=target.role.value, permissions=sorted(perms))
