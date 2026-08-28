"""The cost and budget API (§6, §7).

**No route here enforces a budget.** These endpoints read cost, manage budget
definitions and report utilization. A budget becomes enforcement only inside
the tool loop, through Phase 4.3's governance engine, which is the single place
on this platform that decides whether an execution may continue. Keeping that
true of the HTTP surface as well as of the loop is the same discipline Phase
4.3 applied to its own routes.

Mounted at ``/api/v1/cost`` and ``/api/v1/budgets``, deliberately clear of the
legacy ``/analytics/cost``, which stays exactly where it is — still
working, now carrying a deprecation marker (M4-4.4-FR-040).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.finops.aggregation import CostAggregator, CostDimensionError, CostFilters
from app.finops.budgets import BudgetService
from app.finops.schemas import (
    BudgetCreate,
    BudgetRead,
    BudgetUpdate,
    BudgetUtilizationRead,
    CostProvenanceRead,
    CostSummaryRead,
    SpendAnomalyRead,
)
from app.identity.errors import ErrorCode, IdentityError
from app.models.user import User
from app.runtime.deployment.idempotency import IdempotencyService

router = APIRouter(prefix="/api/v1", tags=["cost-governance"])

# `runtime.cost.view` already existed, and its catalog description already read
# "View runtime cost and token usage" -- exactly this capability. Reused rather
# than shadowed by a synonym, for the reason Phase 4.2 gave when it declined to
# register `runtime.observability.view`: two codes guarding one capability is
# how an authorization model drifts from what operators believe they granted.
_COST_VIEW = "runtime.cost.view"

# Budgets do need their own codes. Reading a spend figure and configuring a
# ceiling that can stop production are different powers, and the second is a
# finance/admin decision rather than an observability one.
_BUDGET_VIEW = "runtime.budget.view"
_BUDGET_MANAGE = "runtime.budget.manage"


def _filters(agent_id, agent_version_id, deployment_id, environment, provider, model,
             project_id, department_id, started_after, started_before) -> CostFilters:
    return CostFilters(
        agent_id=agent_id, agent_version_id=agent_version_id, deployment_id=deployment_id,
        environment=environment, provider=provider, model=model, project_id=project_id,
        department_id=department_id, started_after=started_after, started_before=started_before,
    )


@router.get("/cost/summary", response_model=CostSummaryRead)
def cost_summary(
    dimension: str | None = Query(default=None,
                                  description="agent|agent_version|environment|provider|model|project|department|status"),
    agent_id: uuid.UUID | None = Query(default=None),
    agent_version_id: uuid.UUID | None = Query(default=None),
    deployment_id: uuid.UUID | None = Query(default=None),
    environment: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    model: str | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    department_id: uuid.UUID | None = Query(default=None),
    started_after: datetime | None = Query(default=None),
    started_before: datetime | None = Query(default=None),
    actor: User = Depends(require_permission(_COST_VIEW)),
    db: Session = Depends(get_db),
):
    """Real per-execution spend, aggregated (M4-4.4-FR-001).

    Every figure comes from ``agent_executions.cost_amount``. Nothing here
    reads the legacy estimated analytics, and nothing recomputes a price."""
    try:
        return CostAggregator(db).summary(
            actor.organization_id, dimension=dimension,
            filters=_filters(agent_id, agent_version_id, deployment_id, environment, provider,
                             model, project_id, department_id, started_after, started_before),
        ).as_dict()
    except CostDimensionError as exc:
        raise IdentityError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc


@router.get("/cost/timeseries")
def cost_timeseries(
    granularity: str = Query(default="day", description="hour|day|month"),
    agent_id: uuid.UUID | None = Query(default=None),
    agent_version_id: uuid.UUID | None = Query(default=None),
    deployment_id: uuid.UUID | None = Query(default=None),
    environment: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    model: str | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    department_id: uuid.UUID | None = Query(default=None),
    started_after: datetime | None = Query(default=None),
    started_before: datetime | None = Query(default=None),
    actor: User = Depends(require_permission(_COST_VIEW)),
    db: Session = Depends(get_db),
):
    try:
        points = CostAggregator(db).timeseries(
            actor.organization_id, granularity=granularity,
            filters=_filters(agent_id, agent_version_id, deployment_id, environment, provider,
                             model, project_id, department_id, started_after, started_before),
        )
    except CostDimensionError as exc:
        raise IdentityError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
    return [point.as_dict() for point in points]


@router.get("/cost/anomalies", response_model=list[SpendAnomalyRead])
def cost_anomalies(
    granularity: str = Query(default="day"),
    threshold_ratio: float = Query(default=3.0, gt=1.0),
    min_baseline: float = Query(default=0.0, ge=0.0),
    started_after: datetime | None = Query(default=None),
    started_before: datetime | None = Query(default=None),
    actor: User = Depends(require_permission(_COST_VIEW)),
    db: Session = Depends(get_db),
):
    """Deterministic spend spikes (M4-4.4-FR-003).

    Every anomaly returns the amount, the baseline it was compared against, the
    ratio and the threshold, so an operator can check the arithmetic by hand.
    A cost alert nobody can reproduce is a cost alert nobody trusts."""
    try:
        found = CostAggregator(db).anomalies(
            actor.organization_id, granularity=granularity,
            threshold_ratio=threshold_ratio, min_baseline=min_baseline,
            filters=_filters(None, None, None, None, None, None, None, None,
                             started_after, started_before),
        )
    except CostDimensionError as exc:
        raise IdentityError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc
    return [item.as_dict() for item in found]


@router.get("/cost/executions/{execution_id}/provenance", response_model=CostProvenanceRead)
def cost_provenance(
    execution_id: uuid.UUID,
    actor: User = Depends(require_permission(_COST_VIEW)),
    db: Session = Depends(get_db),
):
    """§10 — how this charge was arrived at, after the fact."""
    record = CostAggregator(db).provenance(actor.organization_id, execution_id)
    if record is None:
        raise IdentityError(ErrorCode.EXECUTION_NOT_FOUND, "Execution not found.")
    return record


# --------------------------------------------------------------------------- #
# Budgets
# --------------------------------------------------------------------------- #
@router.get("/budgets", response_model=list[BudgetRead])
def list_budgets(
    enabled: bool | None = Query(default=None),
    scope_type: str | None = Query(default=None),
    actor: User = Depends(require_permission(_BUDGET_VIEW)),
    db: Session = Depends(get_db),
):
    return BudgetService(db).list(actor, enabled=enabled, scope_type=scope_type)


@router.post("/budgets", response_model=BudgetRead, status_code=status.HTTP_201_CREATED)
def create_budget(
    payload: BudgetCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(require_permission(_BUDGET_MANAGE)),
    db: Session = Depends(get_db),
):
    """Reuses Phase 3.1's platform-wide idempotency contract: a retried create
    must not leave two ceilings where the operator asked for one, because both
    would be evaluated and the tighter would fire with no obvious explanation."""
    service = BudgetService(db)

    def _create() -> dict:
        return {"budget_id": str(service.create(actor, payload.model_dump()).id)}

    result, _replayed = IdempotencyService(db).execute(
        organization_id=actor.organization_id, operation="finops.budget.create",
        key=idempotency_key, payload=payload.model_dump(mode="json"), fn=_create,
    )
    return service.get_or_404(actor, uuid.UUID(result["budget_id"]))


@router.get("/budgets/{budget_id}", response_model=BudgetRead)
def get_budget(
    budget_id: uuid.UUID,
    actor: User = Depends(require_permission(_BUDGET_VIEW)),
    db: Session = Depends(get_db),
):
    return BudgetService(db).get_or_404(actor, budget_id)


@router.patch("/budgets/{budget_id}", response_model=BudgetRead)
def update_budget(
    budget_id: uuid.UUID,
    payload: BudgetUpdate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(require_permission(_BUDGET_MANAGE)),
    db: Session = Depends(get_db),
):
    service = BudgetService(db)
    changes = payload.model_dump(exclude_unset=True)

    def _update() -> dict:
        return {"budget_id": str(service.update(actor, budget_id, changes).id)}

    IdempotencyService(db).execute(
        organization_id=actor.organization_id, operation="finops.budget.update",
        key=idempotency_key, payload=payload.model_dump(mode="json", exclude_unset=True),
        fn=_update,
    )
    return service.get_or_404(actor, budget_id)


@router.delete("/budgets/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(
    budget_id: uuid.UUID,
    actor: User = Depends(require_permission(_BUDGET_MANAGE)),
    db: Session = Depends(get_db),
):
    """Disables rather than deletes — a budget's reservations are the record of
    money actually spent under it, and a cascade would erase that."""
    BudgetService(db).delete(actor, budget_id)


@router.get("/budgets/{budget_id}/utilization", response_model=BudgetUtilizationRead)
def budget_utilization(
    budget_id: uuid.UUID,
    execution_id: uuid.UUID | None = Query(
        default=None, description="Required for an EXECUTION-period budget."),
    actor: User = Depends(require_permission(_BUDGET_VIEW)),
    db: Session = Depends(get_db),
):
    """M4-4.4-FR-013 — spent / reserved / remaining.

    ``spent`` and ``reserved`` are separate numbers because they answer
    different questions: one is money that is gone, the other is money that
    might still be released."""
    service = BudgetService(db)
    budget = service.get_or_404(actor, budget_id)
    return service.utilization(budget, execution_id=execution_id).as_dict()
