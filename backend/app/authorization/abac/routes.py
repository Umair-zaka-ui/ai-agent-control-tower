"""ABAC engine API (Phase 4.3.5 §30, §37).

Policies (CRUD + lifecycle + versions + rollback), the attribute catalog,
simulation, evaluation and policy exceptions — all under
``/api/v1/authorization`` and gated by the §37 permission set (authoring and
publishing are separable for segregation of duties).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization.abac.attributes import AttributeRegistryService
from app.authorization.abac.engine import ABACEngine, ABACMetrics, PolicySimulationService
from app.authorization.abac.enums import ABACAuditEvent
from app.authorization.abac.policies import PolicyService, record_abac_event
from app.authorization.abac.schemas import (
    ABACDecisionRead,
    AttributeCreate,
    AttributeRead,
    AttributeUpdate,
    EvaluateRequest,
    EvaluationRead,
    ExceptionCreate,
    ExceptionRead,
    PolicyRead,
    PolicyVersionRead,
    PolicyWrite,
    SimulateRequest,
    SimulationRead,
    ValidationResult,
)
from app.core.database import get_db
from app.identity.api.deps import get_current_user, require_permission
from app.identity.errors import ErrorCode, IdentityError
from app.models.abac import ABACEvaluation, ABACPolicyException
from app.models.resource_authorization import ProtectedResource
from app.models.user import User

router = APIRouter(prefix="/api/v1/authorization", tags=["abac"])

_VIEW = "authorization.abac.view"
_CREATE = "authorization.abac.create"
_UPDATE = "authorization.abac.update"
_PUBLISH = "authorization.abac.publish"
_DISABLE = "authorization.abac.disable"
_ARCHIVE = "authorization.abac.archive"
_SIMULATE = "authorization.abac.simulate"
_AUDIT = "authorization.abac.audit"
_ATTR_MANAGE = "authorization.attribute.manage"
_EXC_MANAGE = "authorization.exception.manage"


def _is_platform_admin(db: Session, actor: User) -> bool:
    from app.authorization.engine import GLOBAL_WILDCARD, PermissionEngine

    return any(g.pattern == GLOBAL_WILDCARD for g in PermissionEngine(db).resolve_grants(actor))


def _resource(db: Session, actor: User, resource_pk: uuid.UUID | None) -> ProtectedResource | None:
    if resource_pk is None:
        return None
    from app.authorization.resources.services import ResourceRegistryService

    return ResourceRegistryService(db).get(actor, resource_pk)


def _decision_read(result) -> ABACDecisionRead:
    return ABACDecisionRead(
        decision=result.decision, allowed=result.allowed, reason=result.reason,
        matched_policies=result.matched_policies, obligations=result.obligations,
        explanation=result.explanation, evaluation_time_ms=result.evaluation_time_ms,
        request_id=result.request_id, applicable=result.applicable,
    )


# --------------------------------------------------------------------------- #
# Policies (§30)
# --------------------------------------------------------------------------- #
@router.get("/abac/policies", response_model=list[PolicyRead])
def list_policies(
    status_filter: str | None = Query(default=None, alias="status"),
    actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db),
):
    return PolicyService(db).list(actor, status=status_filter)


@router.post("/abac/policies", response_model=PolicyRead, status_code=status.HTTP_201_CREATED)
def create_policy(
    payload: PolicyWrite,
    actor: User = Depends(require_permission(_CREATE)), db: Session = Depends(get_db),
):
    p = PolicyService(db).create(actor, payload.model_dump(exclude_none=True),
                                 is_platform_admin=_is_platform_admin(db, actor))
    db.commit()
    return p


@router.get("/abac/policies/{policy_id}", response_model=PolicyRead)
def get_policy(
    policy_id: uuid.UUID,
    actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db),
):
    return PolicyService(db).get(actor, policy_id)


@router.put("/abac/policies/{policy_id}", response_model=PolicyRead)
def update_policy(
    policy_id: uuid.UUID, payload: PolicyWrite,
    actor: User = Depends(require_permission(_UPDATE)), db: Session = Depends(get_db),
):
    p = PolicyService(db).update(actor, policy_id, payload.model_dump(exclude_none=True))
    db.commit()
    return p


@router.delete("/abac/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT,
               response_class=Response)
def delete_policy(
    policy_id: uuid.UUID,
    actor: User = Depends(require_permission(_ARCHIVE)), db: Session = Depends(get_db),
) -> Response:
    PolicyService(db).delete(actor, policy_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Lifecycle ---------------------------------------------------------------- #
@router.post("/abac/policies/{policy_id}/validate", response_model=ValidationResult)
def validate_policy(
    policy_id: uuid.UUID,
    actor: User = Depends(require_permission(_UPDATE)), db: Session = Depends(get_db),
):
    p, errors = PolicyService(db).validate(actor, policy_id)
    db.commit()
    return ValidationResult(policy_id=p.id, valid=not errors, status=p.status, errors=errors)


@router.post("/abac/policies/{policy_id}/publish", response_model=PolicyRead)
def publish_policy(
    policy_id: uuid.UUID,
    actor: User = Depends(require_permission(_PUBLISH)), db: Session = Depends(get_db),
):
    p = PolicyService(db).publish(actor, policy_id,
                                  is_platform_admin=_is_platform_admin(db, actor))
    db.commit()
    return p


@router.post("/abac/policies/{policy_id}/disable", response_model=PolicyRead)
def disable_policy(
    policy_id: uuid.UUID,
    actor: User = Depends(require_permission(_DISABLE)), db: Session = Depends(get_db),
):
    p = PolicyService(db).disable(actor, policy_id)
    db.commit()
    return p


@router.post("/abac/policies/{policy_id}/archive", response_model=PolicyRead)
def archive_policy(
    policy_id: uuid.UUID,
    actor: User = Depends(require_permission(_ARCHIVE)), db: Session = Depends(get_db),
):
    p = PolicyService(db).archive(actor, policy_id)
    db.commit()
    return p


@router.post("/abac/policies/{policy_id}/clone", response_model=PolicyRead,
             status_code=status.HTTP_201_CREATED)
def clone_policy(
    policy_id: uuid.UUID,
    actor: User = Depends(require_permission(_CREATE)), db: Session = Depends(get_db),
):
    p = PolicyService(db).clone(actor, policy_id)
    db.commit()
    return p


# --- Versions ------------------------------------------------------------------- #
@router.get("/abac/policies/{policy_id}/versions", response_model=list[PolicyVersionRead])
def list_versions(
    policy_id: uuid.UUID,
    actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db),
):
    return PolicyService(db).versions(actor, policy_id)


@router.get("/abac/policies/{policy_id}/versions/{version}", response_model=PolicyVersionRead)
def get_version(
    policy_id: uuid.UUID, version: int,
    actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db),
):
    rows = PolicyService(db).versions(actor, policy_id)
    for row in rows:
        if row.version == version:
            return row
    raise IdentityError(ErrorCode.ABAC_POLICY_NOT_FOUND, "Version not found.")


@router.post("/abac/policies/{policy_id}/rollback/{version}", response_model=PolicyRead)
def rollback_policy(
    policy_id: uuid.UUID, version: int,
    actor: User = Depends(require_permission(_PUBLISH)), db: Session = Depends(get_db),
):
    p = PolicyService(db).rollback(actor, policy_id, version,
                                   is_platform_admin=_is_platform_admin(db, actor))
    db.commit()
    return p


# --------------------------------------------------------------------------- #
# Simulation (§35) — read-only, never executes the action.
# --------------------------------------------------------------------------- #
def _simulate(actor: User, db: Session, payload: SimulateRequest,
              draft_policy: dict | None) -> SimulationRead:
    subject = actor
    if payload.identity_id is not None and payload.identity_id != actor.id:
        subject = db.get(User, payload.identity_id)
        if subject is None or subject.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.USER_NOT_FOUND, "Identity not found.")
    resource = _resource(db, actor, payload.resource_pk)
    result = PolicySimulationService(db).simulate(
        actor, subject=subject, action=payload.action, resource=resource,
        overrides=payload.context, draft_policy=draft_policy,
    )
    db.commit()  # persists only the ABAC_POLICY_SIMULATED audit event
    return SimulationRead(
        baseline_rbac=result["baseline_rbac"],
        resource_authorization=result["resource_authorization"],
        abac=_decision_read(result["abac"]),
    )


@router.post("/abac/simulate", response_model=SimulationRead)
def simulate(
    payload: SimulateRequest,
    actor: User = Depends(require_permission(_SIMULATE)), db: Session = Depends(get_db),
):
    return _simulate(actor, db, payload, payload.policy)


@router.post("/abac/policies/{policy_id}/simulate", response_model=SimulationRead)
def simulate_policy(
    policy_id: uuid.UUID, payload: SimulateRequest,
    actor: User = Depends(require_permission(_SIMULATE)), db: Session = Depends(get_db),
):
    p = PolicyService(db).get(actor, policy_id)
    draft = {
        "id": str(p.id), "name": p.name, "effect": p.effect, "priority": p.priority,
        "combining_algorithm": p.combining_algorithm, "conditions": p.conditions,
        "obligations": p.obligations,
    }
    return _simulate(actor, db, payload, draft)


# --------------------------------------------------------------------------- #
# Evaluation (§30, §31) — live PDP decision for the caller.
# --------------------------------------------------------------------------- #
@router.post("/abac/evaluate", response_model=ABACDecisionRead)
def evaluate(
    payload: EvaluateRequest, request: Request,
    actor: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    resource = _resource(db, actor, payload.resource_pk)
    result = ABACEngine(db).evaluate(
        actor, payload.action, resource, overrides=payload.context,
        ip_address=request.client.host if request.client else None,
        request_id=request.headers.get("x-request-id"),
        correlation_id=request.headers.get("x-correlation-id"),
    )
    db.commit()
    return _decision_read(result)


@router.get("/abac/evaluations", response_model=list[EvaluationRead])
def list_evaluations(
    decision: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    actor: User = Depends(require_permission(_AUDIT)), db: Session = Depends(get_db),
):
    q = select(ABACEvaluation).where(
        ABACEvaluation.organization_id == actor.organization_id
    ).order_by(ABACEvaluation.created_at.desc()).limit(limit)
    if decision:
        q = q.where(ABACEvaluation.decision == decision.upper())
    return list(db.execute(q).scalars())


@router.get("/abac/evaluations/{evaluation_id}", response_model=EvaluationRead)
def get_evaluation(
    evaluation_id: uuid.UUID,
    actor: User = Depends(require_permission(_AUDIT)), db: Session = Depends(get_db),
):
    row = db.get(ABACEvaluation, evaluation_id)
    if row is None or row.organization_id != actor.organization_id:
        raise IdentityError(ErrorCode.ABAC_POLICY_NOT_FOUND, "Evaluation not found.")
    return row


@router.get("/abac/metrics")
def abac_metrics(actor: User = Depends(require_permission(_VIEW))) -> dict:
    """§43 — evaluation counters, latency and cache hit ratio."""
    return ABACMetrics.snapshot()


# --------------------------------------------------------------------------- #
# Attribute catalog (§20, §30)
# --------------------------------------------------------------------------- #
@router.get("/attributes", response_model=list[AttributeRead])
def list_attributes(
    category: str | None = Query(default=None),
    actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db),
):
    rows = AttributeRegistryService(db).list(category=category)
    db.commit()  # persists idempotent system seeding
    return rows


@router.get("/attributes/{name}", response_model=AttributeRead)
def get_attribute(
    name: str,
    actor: User = Depends(require_permission(_VIEW)), db: Session = Depends(get_db),
):
    d = AttributeRegistryService(db).by_name(name)
    if d is None:
        raise IdentityError(ErrorCode.ABAC_ATTRIBUTE_NOT_FOUND, "Attribute not found.")
    return d


@router.post("/attributes", response_model=AttributeRead, status_code=status.HTTP_201_CREATED)
def create_attribute(
    payload: AttributeCreate,
    actor: User = Depends(require_permission(_ATTR_MANAGE)), db: Session = Depends(get_db),
):
    d = AttributeRegistryService(db).create(
        actor.id, name=payload.name, category=payload.category, data_type=payload.data_type,
        description=payload.description, sensitivity=payload.sensitivity,
        supported_operators=payload.supported_operators,
    )
    record_abac_event(db, ABACAuditEvent.ATTRIBUTE_DEFINITION_CREATED,
                      organization_id=actor.organization_id, actor_id=actor.id,
                      meta={"attribute": d.name})
    db.commit()
    return d


@router.put("/attributes/{definition_id}", response_model=AttributeRead)
def update_attribute(
    definition_id: uuid.UUID, payload: AttributeUpdate,
    actor: User = Depends(require_permission(_ATTR_MANAGE)), db: Session = Depends(get_db),
):
    d = AttributeRegistryService(db).update(
        definition_id, description=payload.description, sensitivity=payload.sensitivity,
        supported_operators=payload.supported_operators, enabled=payload.enabled,
    )
    record_abac_event(db, ABACAuditEvent.ATTRIBUTE_DEFINITION_UPDATED,
                      organization_id=actor.organization_id, actor_id=actor.id,
                      meta={"attribute": d.name})
    db.commit()
    return d


# --------------------------------------------------------------------------- #
# Policy exceptions (§21) — disabled unless explicitly approved & time-boxed.
# --------------------------------------------------------------------------- #
@router.get("/exceptions", response_model=list[ExceptionRead])
def list_exceptions(
    actor: User = Depends(require_permission(_EXC_MANAGE)), db: Session = Depends(get_db),
):
    svc = PolicyService(db)
    rows = list(db.execute(
        select(ABACPolicyException).order_by(ABACPolicyException.created_at.desc())
    ).scalars())
    # Tenant isolation: only exceptions whose policy the caller can see.
    visible = []
    for row in rows:
        try:
            svc.get(actor, row.policy_id)
        except IdentityError:
            continue
        visible.append(row)
    return visible


@router.post("/exceptions", response_model=ExceptionRead, status_code=status.HTTP_201_CREATED)
def create_exception(
    payload: ExceptionCreate,
    actor: User = Depends(require_permission(_EXC_MANAGE)), db: Session = Depends(get_db),
):
    PolicyService(db).get(actor, payload.policy_id)  # tenancy check
    if payload.valid_until is None:
        raise IdentityError(ErrorCode.VALIDATION_ERROR,
                            "Policy exceptions must have an expiry (valid_until).")
    exc = ABACPolicyException(
        policy_id=payload.policy_id, subject_type=payload.subject_type.upper(),
        subject_id=payload.subject_id, resource_type=payload.resource_type,
        resource_id=payload.resource_id, reason=payload.reason, approved_by=actor.id,
        valid_from=payload.valid_from, valid_until=payload.valid_until, status="ACTIVE",
    )
    db.add(exc)
    db.flush()
    record_abac_event(db, ABACAuditEvent.POLICY_EXCEPTION_CREATED,
                      organization_id=actor.organization_id, actor_id=actor.id,
                      meta={"exception_id": str(exc.id), "policy_id": str(payload.policy_id),
                            "subject_id": str(payload.subject_id)})
    db.commit()
    return exc


@router.delete("/exceptions/{exception_id}", response_model=ExceptionRead)
def revoke_exception(
    exception_id: uuid.UUID,
    actor: User = Depends(require_permission(_EXC_MANAGE)), db: Session = Depends(get_db),
):
    exc = db.get(ABACPolicyException, exception_id)
    if exc is None:
        raise IdentityError(ErrorCode.ABAC_POLICY_NOT_FOUND, "Exception not found.")
    PolicyService(db).get(actor, exc.policy_id)  # tenancy check
    exc.status = "REVOKED"
    db.commit()
    return exc
