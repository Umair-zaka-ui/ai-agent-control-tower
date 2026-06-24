"""Policy routes - CRUD for database-driven governance policies."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.database import get_db
from app.core.enums import ActorType
from app.models.policy import Policy
from app.models.user import User
from app.schemas.policy import PolicyCreate, PolicyRead, PolicyUpdate
from app.services import audit_service

router = APIRouter(prefix="/policies", tags=["policies"])


@router.post("", response_model=PolicyRead, status_code=status.HTTP_201_CREATED)
def create_policy(
    payload: PolicyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("policy.create")),
) -> Policy:
    policy = Policy(
        organization_id=current_user.organization_id,
        name=payload.name,
        description=payload.description,
        resource=payload.resource,
        action=payload.action,
        conditions=payload.conditions,
        decision=payload.decision.value,
        priority=payload.priority,
        enabled=payload.enabled,
    )
    db.add(policy)
    db.flush()
    audit_service.log_event(
        db,
        organization_id=current_user.organization_id,
        actor_type=ActorType.USER,
        actor_id=current_user.id,
        event_type="POLICY_CREATED",
        entity_type="policy",
        entity_id=policy.id,
        metadata={"name": policy.name, "resource": policy.resource, "action": policy.action},
    )
    db.commit()
    return policy


@router.get("", response_model=list[PolicyRead])
def list_policies(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("policy.view")),
    resource: str | None = Query(default=None),
    action: str | None = Query(default=None),
) -> list[Policy]:
    stmt = select(Policy).where(Policy.organization_id == current_user.organization_id)
    if resource is not None:
        stmt = stmt.where(Policy.resource == resource)
    if action is not None:
        stmt = stmt.where(Policy.action == action)
    stmt = stmt.order_by(Policy.priority.desc(), Policy.created_at)
    return list(db.execute(stmt).scalars().all())


@router.get("/{policy_id}", response_model=PolicyRead)
def get_policy(
    policy_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("policy.view")),
) -> Policy:
    return _get_org_policy(db, policy_id, current_user)


@router.patch("/{policy_id}", response_model=PolicyRead)
def update_policy(
    policy_id: uuid.UUID,
    payload: PolicyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("policy.edit")),
) -> Policy:
    policy = _get_org_policy(db, policy_id, current_user)
    data = payload.model_dump(exclude_unset=True)
    if "decision" in data and data["decision"] is not None:
        data["decision"] = data["decision"].value
    for field, value in data.items():
        setattr(policy, field, value)
    db.flush()
    audit_service.log_event(
        db,
        organization_id=current_user.organization_id,
        actor_type=ActorType.USER,
        actor_id=current_user.id,
        event_type="POLICY_UPDATED",
        entity_type="policy",
        entity_id=policy.id,
        metadata={"updated_fields": list(data.keys())},
    )
    db.commit()
    return policy


@router.delete("/{policy_id}")
def delete_policy(
    policy_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("policy.delete")),
) -> dict[str, bool]:
    policy = _get_org_policy(db, policy_id, current_user)
    name = policy.name
    db.delete(policy)
    audit_service.log_event(
        db,
        organization_id=current_user.organization_id,
        actor_type=ActorType.USER,
        actor_id=current_user.id,
        event_type="POLICY_DELETED",
        entity_type="policy",
        entity_id=policy_id,
        metadata={"name": name},
    )
    db.commit()
    return {"deleted": True}


def _get_org_policy(db: Session, policy_id: uuid.UUID, user: User) -> Policy:
    policy = db.get(Policy, policy_id)
    if policy is None or policy.organization_id != user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found.")
    return policy
