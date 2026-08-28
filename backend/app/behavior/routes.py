"""The behavioral signals API (§6, §7).

**No route here enforces anything.** These endpoints read findings and run an
on-demand evaluation. A finding is a signal; Phase 4.3's governance engine
remains the only thing that can stop an execution, and keeping that true of the
HTTP surface as well as of the loop is the discipline Phases 4.3 and 4.4 both
applied to their own routes.

``POST /behavior/evaluate`` is the **interim** trigger. Phase 3.8 built the
distributed scheduler that should drive this on a timer, and wiring it there is
that phase's registry work rather than this one's — so the operation is built
idempotent and bounded, exactly as Phase 3.5's auto-advance and Phase 3.7's
trigger evaluation were, and is marked for the scheduler to adopt. Building a
second scheduler here would be the fork this milestone has refused three times.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.behavior.engine import DEFAULT_WINDOW, MAX_WINDOW, BehavioralEvaluator
from app.behavior.schemas import (
    BehavioralEvaluationRead,
    BehavioralFindingRead,
    EvaluateRequest,
)
from app.behavior.signals import SIGNAL_TYPES
from app.behavior.states import SignalState
from app.identity.errors import ErrorCode, IdentityError
from app.models.runtime import BehavioralFinding
from app.models.user import User
from app.runtime.deployment.idempotency import IdempotencyService
from app.runtime.services import AgentRegistryService

router = APIRouter(prefix="/api/v1/runtime", tags=["behavioral-signals"])

# `runtime.telemetry.view` already existed and its catalog description already
# reads "View runtime telemetry and execution traces". A behavioral finding is
# derived telemetry about an execution stream -- the same plane, the same
# capability -- so it is reused rather than shadowed by a synonym, for the
# reason Phase 4.2 gave when it declined to register `runtime.observability.view`
# and Phase 4.4 gave when it reused `runtime.cost.view`. No new permission.
_BEHAVIOR_VIEW = "runtime.telemetry.view"

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50


@router.get("/behavior/findings", response_model=list[BehavioralFindingRead])
def list_findings(
    agent_id: uuid.UUID | None = Query(default=None),
    agent_version_id: uuid.UUID | None = Query(default=None),
    environment_id: uuid.UUID | None = Query(default=None),
    signal_type: str | None = Query(default=None),
    state: str | None = Query(default=None),
    evaluated_after: datetime | None = Query(default=None),
    evaluated_before: datetime | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    actor: User = Depends(require_permission(_BEHAVIOR_VIEW)),
    db: Session = Depends(get_db),
):
    """Findings for this tenant, newest first.

    The tenant predicate leads every statement and is not optional — there is
    no code path here that builds a query without it, which is both the
    isolation property and the reason the plan starts from
    ``ix_behavioral_findings_org_evaluated``."""
    if signal_type is not None and signal_type not in SIGNAL_TYPES:
        raise IdentityError(ErrorCode.VALIDATION_ERROR,
                            f"Unknown signal_type '{signal_type}'. Known: {', '.join(SIGNAL_TYPES)}.")
    if state is not None and state not in {s.value for s in SignalState}:
        raise IdentityError(ErrorCode.VALIDATION_ERROR,
                            f"Unknown state '{state}'.")

    stmt = select(BehavioralFinding).where(
        BehavioralFinding.organization_id == actor.organization_id)
    if agent_id:
        stmt = stmt.where(BehavioralFinding.agent_id == agent_id)
    if agent_version_id:
        stmt = stmt.where(BehavioralFinding.agent_version_id == agent_version_id)
    if environment_id:
        stmt = stmt.where(BehavioralFinding.environment_id == environment_id)
    if signal_type:
        stmt = stmt.where(BehavioralFinding.signal_type == signal_type)
    if state:
        stmt = stmt.where(BehavioralFinding.state == state)
    if evaluated_after:
        stmt = stmt.where(BehavioralFinding.evaluated_at >= evaluated_after)
    if evaluated_before:
        stmt = stmt.where(BehavioralFinding.evaluated_at <= evaluated_before)

    return list(db.execute(
        stmt.order_by(BehavioralFinding.evaluated_at.desc(), BehavioralFinding.id.desc())
        .limit(limit).offset(offset)
    ).scalars())


@router.get("/agents/{agent_id}/behavior", response_model=list[BehavioralFindingRead])
def agent_behavior(
    agent_id: uuid.UUID,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    actor: User = Depends(require_permission(_BEHAVIOR_VIEW)),
    db: Session = Depends(get_db),
):
    """One agent's behavioral findings.

    Resolved through ``AgentRegistryService.get_or_404``, so another tenant's
    agent is *not found* rather than empty — refusing to confirm existence, not
    merely to read (§34)."""
    agent = AgentRegistryService(db).get_or_404(actor, agent_id)
    return list(db.execute(
        select(BehavioralFinding)
        .where(BehavioralFinding.organization_id == actor.organization_id,
               BehavioralFinding.agent_id == agent.id)
        .order_by(BehavioralFinding.evaluated_at.desc(), BehavioralFinding.id.desc())
        .limit(limit)
    ).scalars())


@router.post("/behavior/evaluate", response_model=BehavioralEvaluationRead,
             status_code=status.HTTP_200_OK)
def evaluate_behavior(
    payload: EvaluateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(require_permission(_BEHAVIOR_VIEW)),
    db: Session = Depends(get_db),
):
    """Run one evaluation now (M4-4.5-FR-001).

    **Interim, and marked as such**: Phase 3.8's distributed scheduler is what
    should drive this on a timer. It is idempotent at two levels so adopting it
    there is a registration rather than a rewrite — Phase 3.1's
    ``Idempotency-Key`` contract on the request, and a unique constraint on
    ``(agent, signal, window)`` beneath it. A scheduler run that overlaps or
    retries produces one finding per window either way.

    Evaluation failure is **non-gating**: it produces no finding and cannot
    affect any execution. Behavioral signals are telemetry-plane, and the
    telemetry plane fails open (§9)."""
    agent = AgentRegistryService(db).get_or_404(actor, payload.agent_id)
    window = timedelta(days=payload.window_days) if payload.window_days else DEFAULT_WINDOW
    if window > MAX_WINDOW:
        raise IdentityError(
            ErrorCode.VALIDATION_ERROR,
            f"window_days may not exceed {MAX_WINDOW.days}.")

    evaluator = BehavioralEvaluator(db)

    def _run() -> dict:
        result = evaluator.evaluate(
            organization_id=actor.organization_id, agent=agent,
            window=window, environment=None)
        return {
            "agent_id": str(result.agent_id),
            "window_start": result.window_start.isoformat(),
            "window_end": result.window_end.isoformat(),
            "sample_count": result.candidate.sample_count,
            "baseline_sample_count": (
                result.baseline.sample_count if result.baseline else 0),
            "signals": [
                {
                    "signal_type": signal.signal_type, "metric": signal.metric,
                    "state": signal.state.value, "reason": signal.reason,
                    "observed_value": signal.observed,
                    "threshold_value": signal.threshold,
                    "baseline_value": signal.baseline,
                    "attribution": signal.attribution,
                }
                for signal in result.results
            ],
            "findings_recorded": len(result.reportable),
        }

    body, _replayed = IdempotencyService(db).execute(
        organization_id=actor.organization_id, operation="behavior.evaluate",
        key=idempotency_key, payload=payload.model_dump(mode="json"), fn=_run,
    )
    return body
