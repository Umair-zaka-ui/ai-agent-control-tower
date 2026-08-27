"""The runtime governance API (§6, §7).

**Enforcement is not here.** The engine runs inside the tool loop; these routes
configure it and read what it decided. That separation is deliberate — an
endpoint that could evaluate a checkpoint would be a second way into the
enforcement path, which is exactly what this phase exists to prevent.

Mounted on the existing ``/api/v1/runtime`` prefix rather than a new one. The
build prompt's ``/api/v1/executions/{id}/governance-decisions`` would have
created a second, prefix-less execution namespace alongside the established
``/api/v1/runtime/executions/{id}/...`` family; the deviation and its reasoning
are recorded in this phase's report.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.models.runtime import RuntimeGovernanceDecision
from app.models.user import User
from app.runtime.deployment.idempotency import IdempotencyService
from app.runtime.governance.policies import GovernancePolicyService
from app.runtime.governance.schemas import (
    GovernanceDecisionRead,
    GovernancePolicyCreate,
    GovernancePolicyRead,
    GovernancePolicyUpdate,
)
from app.runtime.services import ExecutionRequestService

router = APIRouter(prefix="/api/v1/runtime", tags=["runtime-governance"])

# One new permission, not a family. `runtime.governance.manage` guards writing
# the rules that can halt executions -- a capability nothing existing covers,
# so it earns its own code.
_GOVERNANCE_MANAGE = "runtime.governance.manage"

# Reads reuse `runtime.execution.view`, whose catalog description already reads
# "View executions, tool calls and telemetry". A governance decision is a fact
# about an execution, visible to whoever may see that execution's tool calls;
# minting a second code for it would be permission inflation of exactly the
# kind §16 warns about, and would leave operators holding execution-view
# unable to answer "why did this stop" -- the one question the phase exists to
# answer.
_GOVERNANCE_VIEW = "runtime.execution.view"


@router.get("/governance/policies", response_model=list[GovernancePolicyRead])
def list_governance_policies(
    enabled: bool | None = Query(default=None),
    actor: User = Depends(require_permission(_GOVERNANCE_MANAGE)),
    db: Session = Depends(get_db),
):
    return GovernancePolicyService(db).list(actor, enabled=enabled)


@router.post("/governance/policies", response_model=GovernancePolicyRead,
             status_code=status.HTTP_201_CREATED)
def create_governance_policy(
    payload: GovernancePolicyCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(require_permission(_GOVERNANCE_MANAGE)),
    db: Session = Depends(get_db),
):
    """Reuses Phase 3.1's platform-wide ``Idempotency-Key`` contract rather
    than a local check-then-act, so a retried create cannot produce two
    governance policies with the same intent — two overlapping ceilings would
    both be evaluated, and the operator would see the tighter one fire with no
    obvious explanation."""
    service = GovernancePolicyService(db)
    body = payload.model_dump(mode="json")

    def _create() -> dict:
        return {"policy_id": str(service.create(actor, payload.model_dump()).id)}

    result, _replayed = IdempotencyService(db).execute(
        organization_id=actor.organization_id, operation="runtime.governance.policy.create",
        key=idempotency_key, payload=body, fn=_create,
    )
    return service.get_or_404(actor, uuid.UUID(result["policy_id"]))


@router.get("/governance/policies/{policy_id}", response_model=GovernancePolicyRead)
def get_governance_policy(
    policy_id: uuid.UUID,
    actor: User = Depends(require_permission(_GOVERNANCE_MANAGE)),
    db: Session = Depends(get_db),
):
    return GovernancePolicyService(db).get_or_404(actor, policy_id)


@router.patch("/governance/policies/{policy_id}", response_model=GovernancePolicyRead)
def update_governance_policy(
    policy_id: uuid.UUID,
    payload: GovernancePolicyUpdate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(require_permission(_GOVERNANCE_MANAGE)),
    db: Session = Depends(get_db),
):
    service = GovernancePolicyService(db)
    changes = payload.model_dump(exclude_unset=True)

    def _update() -> dict:
        return {"policy_id": str(service.update(actor, policy_id, changes).id)}

    IdempotencyService(db).execute(
        organization_id=actor.organization_id, operation="runtime.governance.policy.update",
        key=idempotency_key, payload=payload.model_dump(mode="json", exclude_unset=True),
        fn=_update,
    )
    return service.get_or_404(actor, policy_id)


@router.get("/executions/{execution_id}/governance-decisions",
            response_model=list[GovernanceDecisionRead])
def list_governance_decisions(
    execution_id: uuid.UUID,
    actor: User = Depends(require_permission(_GOVERNANCE_VIEW)),
    db: Session = Depends(get_db),
):
    """The append-only lineage for one execution, oldest first — read in the
    order the checkpoints were reached, because the story is chronological.

    Tenant isolation comes from ``get_or_404`` on the execution itself, which
    already reports another tenant's execution as not found (§34); resolving
    the decisions without it would let one tenant confirm another's execution
    id by the difference between a 404 and an empty list."""
    execution = ExecutionRequestService(db).get_or_404(actor, execution_id)
    return list(db.execute(
        select(RuntimeGovernanceDecision)
        .where(RuntimeGovernanceDecision.execution_id == execution.id,
               RuntimeGovernanceDecision.organization_id == actor.organization_id)
        .order_by(RuntimeGovernanceDecision.evaluated_at.asc(),
                  RuntimeGovernanceDecision.id.asc())
    ).scalars())
