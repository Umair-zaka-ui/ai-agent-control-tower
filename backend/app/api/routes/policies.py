"""Policy routes - CRUD, lifecycle, simulation and audit for governance policies."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.enums import (
    ActorType,
    PolicySeverity,
    PolicyStatus,
)
from app.core.database import get_db
from app.core.policy_templates import POLICY_TEMPLATES
from app.models.audit_log import AuditLog
from app.models.policy import Policy
from app.models.user import User
from app.schemas.audit_log import AuditLogRead
from app.schemas.policy import (
    PolicyCreate,
    PolicyRead,
    PolicyTemplate,
    PolicyTestRequest,
    PolicyTestResult,
    PolicyUpdate,
)
from app.services import audit_service
from app.services.policy_engine import evaluate_conditions
from app.services.risk_engine import calculate_risk_score

router = APIRouter(prefix="/policies", tags=["policies"])


def _status_to_enabled(policy_status: PolicyStatus) -> bool:
    return policy_status == PolicyStatus.ENABLED


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
        severity=payload.severity.value,
        status=payload.status.value,
        enabled=_status_to_enabled(payload.status),
        created_by=current_user.id,
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
    search: str | None = Query(default=None),
    resource: str | None = Query(default=None),
    action: str | None = Query(default=None),
    decision: str | None = Query(default=None),
    severity: PolicySeverity | None = Query(default=None),
    status_filter: PolicyStatus | None = Query(default=None, alias="status"),
) -> list[Policy]:
    conditions = [Policy.organization_id == current_user.organization_id]
    if search:
        like = f"%{search.strip()}%"
        conditions.append(
            or_(
                Policy.name.ilike(like),
                Policy.resource.ilike(like),
                Policy.action.ilike(like),
                Policy.description.ilike(like),
                Policy.decision.ilike(like),
            )
        )
    if resource is not None:
        conditions.append(Policy.resource == resource)
    if action is not None:
        conditions.append(Policy.action == action)
    if decision is not None:
        conditions.append(Policy.decision == decision)
    if severity is not None:
        conditions.append(Policy.severity == severity.value)
    if status_filter is not None:
        conditions.append(Policy.status == status_filter.value)

    stmt = (
        select(Policy)
        .where(*conditions)
        .order_by(Policy.priority.desc(), Policy.created_at)
    )
    return list(db.execute(stmt).scalars().all())


@router.get("/templates", response_model=list[PolicyTemplate])
def list_policy_templates(
    current_user: User = Depends(get_current_user),
) -> list[PolicyTemplate]:
    """Built-in policy templates for the create flow."""
    return POLICY_TEMPLATES


@router.get("/{policy_id}", response_model=PolicyRead)
def get_policy(
    policy_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("policy.view")),
) -> Policy:
    return _get_org_policy(db, policy_id, current_user)


@router.api_route("/{policy_id}", methods=["PUT", "PATCH"], response_model=PolicyRead)
def update_policy(
    policy_id: uuid.UUID,
    payload: PolicyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("policy.edit")),
) -> Policy:
    policy = _get_org_policy(db, policy_id, current_user)
    data = payload.model_dump(exclude_unset=True)
    if data.get("decision") is not None:
        data["decision"] = data["decision"].value
    if data.get("severity") is not None:
        data["severity"] = data["severity"].value
    if data.get("status") is not None:
        data["status"] = data["status"].value
        policy.enabled = data["status"] == PolicyStatus.ENABLED.value
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


def _set_enabled(
    db: Session, policy: Policy, user: User, *, enabled: bool, event: str
) -> Policy:
    policy.enabled = enabled
    policy.status = PolicyStatus.ENABLED.value if enabled else PolicyStatus.DISABLED.value
    db.flush()
    audit_service.log_event(
        db,
        organization_id=user.organization_id,
        actor_type=ActorType.USER,
        actor_id=user.id,
        event_type=event,
        entity_type="policy",
        entity_id=policy.id,
        metadata={"name": policy.name},
    )
    db.commit()
    return policy


@router.patch("/{policy_id}/enable", response_model=PolicyRead)
def enable_policy(
    policy_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("policy.edit")),
) -> Policy:
    policy = _get_org_policy(db, policy_id, current_user)
    return _set_enabled(db, policy, current_user, enabled=True, event="POLICY_ENABLED")


@router.patch("/{policy_id}/disable", response_model=PolicyRead)
def disable_policy(
    policy_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("policy.edit")),
) -> Policy:
    policy = _get_org_policy(db, policy_id, current_user)
    return _set_enabled(db, policy, current_user, enabled=False, event="POLICY_DISABLED")


@router.post("/{policy_id}/test", response_model=PolicyTestResult)
def test_policy(
    policy_id: uuid.UUID,
    payload: PolicyTestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("policy.view")),
) -> PolicyTestResult:
    """Simulate an action against this policy and report whether it would trigger."""
    policy = _get_org_policy(db, policy_id, current_user)
    risk_score = calculate_risk_score(payload.resource, payload.action, payload.input_payload)

    audit_service.log_event(
        db,
        organization_id=current_user.organization_id,
        actor_type=ActorType.USER,
        actor_id=current_user.id,
        event_type="POLICY_TESTED",
        entity_type="policy",
        entity_id=policy.id,
        metadata={"resource": payload.resource, "action": payload.action},
    )
    db.commit()

    scoped = policy.resource == payload.resource and policy.action == payload.action
    if not scoped:
        return PolicyTestResult(
            matched=False,
            decision=None,
            reason="Policy does not target this resource/action.",
            risk_score=risk_score,
            triggered_conditions=[],
            explanation=(
                f"This policy applies to {policy.resource}/{policy.action}, "
                f"not {payload.resource}/{payload.action}."
            ),
        )

    conditions_met = evaluate_conditions(policy.conditions, payload.input_payload)
    triggered = _describe_conditions(policy.conditions)
    if conditions_met:
        return PolicyTestResult(
            matched=True,
            decision=policy.decision,
            reason=f"Policy '{policy.name}' matched.",
            risk_score=risk_score,
            triggered_conditions=triggered,
            explanation=(
                f"All conditions held for the input, so the policy applies its "
                f"decision: {policy.decision}."
            ),
        )
    return PolicyTestResult(
        matched=False,
        decision=None,
        reason="Resource/action match but conditions were not satisfied.",
        risk_score=risk_score,
        triggered_conditions=triggered,
        explanation="One or more of the policy's conditions did not hold for this input.",
    )


@router.get("/{policy_id}/audit", response_model=list[AuditLogRead])
def policy_audit(
    policy_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("policy.view")),
) -> list[AuditLog]:
    """Audit-trail entries recorded for this policy."""
    policy = _get_org_policy(db, policy_id, current_user)
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.organization_id == current_user.organization_id,
            AuditLog.entity_type == "policy",
            AuditLog.entity_id == policy.id,
        )
        .order_by(AuditLog.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


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


def _describe_conditions(conditions: dict[str, object]) -> list[str]:
    """Human-readable strings for each condition key (best-effort)."""
    ops = {
        "_gt": "greater than",
        "_gte": "at least",
        "_lt": "less than",
        "_lte": "at most",
        "_ne": "not equal to",
        "_in": "in",
        "_contains": "contains",
        "_eq": "equals",
    }
    out: list[str] = []
    for key, expected in conditions.items():
        matched_op = next((o for o in ops if key.endswith(o)), None)
        if matched_op:
            field = key[: -len(matched_op)]
            out.append(f"{field} {ops[matched_op]} {expected}")
        else:
            out.append(f"{key} equals {expected}")
    return out


def _get_org_policy(db: Session, policy_id: uuid.UUID, user: User) -> Policy:
    policy = db.get(Policy, policy_id)
    if policy is None or policy.organization_id != user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found.")
    return policy
