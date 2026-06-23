"""Permission management routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.core.enums import ActorType, UserRole
from app.models.agent import Agent
from app.models.permission import Permission
from app.models.user import User
from app.schemas.permission import PermissionCreate, PermissionRead
from app.services import audit_service

router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.post("", response_model=PermissionRead, status_code=status.HTTP_201_CREATED)
def create_permission(
    payload: PermissionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN)),
) -> Permission:
    """Create (or update) a permission rule for an agent (ADMIN+ only)."""
    agent = db.get(Agent, payload.agent_id)
    if agent is None or agent.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found."
        )

    # Upsert: a single rule exists per (agent, resource, action).
    existing = db.execute(
        select(Permission).where(
            Permission.agent_id == payload.agent_id,
            Permission.resource == payload.resource,
            Permission.action == payload.action,
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.allowed = payload.allowed
        permission = existing
        event_type = "PERMISSION_UPDATED"
    else:
        permission = Permission(
            organization_id=current_user.organization_id,
            agent_id=payload.agent_id,
            resource=payload.resource,
            action=payload.action,
            allowed=payload.allowed,
        )
        db.add(permission)
        event_type = "PERMISSION_CREATED"

    db.flush()
    audit_service.log_event(
        db,
        organization_id=current_user.organization_id,
        actor_type=ActorType.USER,
        actor_id=current_user.id,
        event_type=event_type,
        entity_type="permission",
        entity_id=permission.id,
        metadata={
            "agent_id": str(permission.agent_id),
            "resource": permission.resource,
            "action": permission.action,
            "allowed": permission.allowed,
        },
    )
    db.commit()
    return permission


@router.get("", response_model=list[PermissionRead])
def list_permissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Permission]:
    """List every permission rule in the caller's organization."""
    stmt = select(Permission).where(
        Permission.organization_id == current_user.organization_id
    ).order_by(Permission.created_at)
    return list(db.execute(stmt).scalars().all())


@router.get("/agent/{agent_id}", response_model=list[PermissionRead])
def list_agent_permissions(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Permission]:
    """List all permission rules for a specific agent."""
    agent = db.get(Agent, agent_id)
    if agent is None or agent.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found."
        )
    stmt = select(Permission).where(Permission.agent_id == agent_id).order_by(
        Permission.created_at
    )
    return list(db.execute(stmt).scalars().all())
