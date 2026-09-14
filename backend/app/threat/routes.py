"""Phase 5.6 (M5.6) - the runtime-threat + containment HTTP surface, under
``/api/v1/threat``.

**Read + triage + containment-execute.** Reading a finding grants nothing.
Containment-execute is a **distinct, stronger permission**
(``containment.execute``) — never implied by ``threat.view``/``threat.manage``
— because it is the one surface in this package that can reach a real
enforcement authority.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.models.agent import Agent
from app.models.threat import ContainmentAction, ThreatFinding
from app.models.user import User
from app.threat.containment import ContainmentOrchestrator
from app.threat.evaluator import ThreatEvaluator
from app.threat.lifecycle import ThreatFindingService
from app.threat.schemas import (
    ContainmentActionRead,
    ContainmentExecuteRequest,
    FindingTransition,
    ThreatFindingRead,
)

router = APIRouter(prefix="/api/v1/threat", tags=["runtime-threat"])

_VIEW = "threat.view"
_MANAGE = "threat.manage"
_CONTAIN = "containment.execute"


def _require_agent(db: Session, actor: User, agent_id: uuid.UUID) -> Agent:
    from app.identity.errors import ErrorCode, IdentityError

    agent = db.get(Agent, agent_id)
    if agent is None or agent.organization_id != actor.organization_id:
        raise IdentityError(ErrorCode.THREAT_SUBJECT_NOT_FOUND, "No such agent in this organization.")
    return agent


@router.get("/findings", response_model=list[ThreatFindingRead])
def list_findings(
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    rule_id: str | None = Query(default=None),
    agent_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    stmt = select(ThreatFinding).where(ThreatFinding.organization_id == actor.organization_id)
    if status:
        stmt = stmt.where(ThreatFinding.status == status)
    if severity:
        stmt = stmt.where(ThreatFinding.severity == severity)
    if rule_id:
        stmt = stmt.where(ThreatFinding.rule_id == rule_id)
    if agent_id:
        stmt = stmt.where(ThreatFinding.agent_id == agent_id)
    stmt = stmt.order_by(ThreatFinding.severity.desc(), ThreatFinding.first_seen_at.desc()).limit(limit)
    return list(db.execute(stmt).scalars())


@router.get("/findings/{finding_id}", response_model=ThreatFindingRead)
def get_finding(
    finding_id: uuid.UUID,
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    return ThreatFindingService(db).get_or_404(actor, finding_id)


def _transition(db: Session, actor: User, finding_id: uuid.UUID, target: str,
                payload: FindingTransition) -> ThreatFinding:
    svc = ThreatFindingService(db)
    finding = svc.get_or_404(actor, finding_id)
    return svc.transition(finding, target, actor.id, note=payload.note)


@router.post("/findings/{finding_id}/acknowledge", response_model=ThreatFindingRead)
def acknowledge_finding(
    finding_id: uuid.UUID,
    payload: FindingTransition = FindingTransition(),
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
):
    return _transition(db, actor, finding_id, "ACKNOWLEDGED", payload)


@router.post("/findings/{finding_id}/resolve", response_model=ThreatFindingRead)
def resolve_finding(
    finding_id: uuid.UUID,
    payload: FindingTransition = FindingTransition(),
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
):
    return _transition(db, actor, finding_id, "RESOLVED", payload)


@router.post("/findings/{finding_id}/suppress", response_model=ThreatFindingRead)
def suppress_finding(
    finding_id: uuid.UUID,
    payload: FindingTransition = FindingTransition(),
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
):
    return _transition(db, actor, finding_id, "SUPPRESSED", payload)


@router.get("/agents/{agent_id}/findings", response_model=list[ThreatFindingRead])
def agent_findings(
    agent_id: uuid.UUID,
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    _require_agent(db, actor, agent_id)
    return list(
        db.execute(
            select(ThreatFinding)
            .where(ThreatFinding.organization_id == actor.organization_id,
                   ThreatFinding.agent_id == agent_id)
            .order_by(ThreatFinding.status, ThreatFinding.severity.desc(),
                      ThreatFinding.first_seen_at.desc())
        ).scalars()
    )


@router.post("/agents/{agent_id}/evaluate")
def evaluate_agent(
    agent_id: uuid.UUID,
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    """Run the deterministic threat rule set for one agent. Idempotent."""
    _require_agent(db, actor, agent_id)
    return ThreatEvaluator(db).evaluate_agent(actor, agent_id).as_dict()


@router.post("/evaluate")
def evaluate_tenant(
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    """The same work the ``threat.evaluate`` scheduler handler does, for
    every non-archived agent in the tenant."""
    return ThreatEvaluator(db).evaluate_tenant(actor).as_dict()


# =========================================================================== #
# Containment -- the distinct, stronger permission
# =========================================================================== #
@router.get("/containment", response_model=list[ContainmentActionRead])
def list_containment_actions(
    status: str | None = Query(default=None),
    agent_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    stmt = select(ContainmentAction).where(ContainmentAction.organization_id == actor.organization_id)
    if status:
        stmt = stmt.where(ContainmentAction.status == status)
    if agent_id:
        stmt = stmt.where(ContainmentAction.agent_id == agent_id)
    stmt = stmt.order_by(ContainmentAction.created_at.desc()).limit(limit)
    return list(db.execute(stmt).scalars())


@router.get("/containment/{action_id}", response_model=ContainmentActionRead)
def get_containment_action(
    action_id: uuid.UUID,
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    from app.identity.errors import ErrorCode, IdentityError

    action = db.get(ContainmentAction, action_id)
    if action is None or action.organization_id != actor.organization_id:
        raise IdentityError(ErrorCode.CONTAINMENT_ACTION_NOT_FOUND, "Containment action not found.")
    return action


@router.post("/agents/{agent_id}/containment", response_model=ContainmentActionRead, status_code=201)
def execute_containment(
    agent_id: uuid.UUID,
    payload: ContainmentExecuteRequest,
    actor: User = Depends(require_permission(_CONTAIN)),
    db: Session = Depends(get_db),
):
    """Execute (or, without ``confirm``, queue) a containment action against
    an agent. Truthful: for an agent ACT does not enforce (control_state !=
    GOVERNED), the response is a REFUSED record naming the real reason, not a
    fake success."""
    _require_agent(db, actor, agent_id)
    return ContainmentOrchestrator(db).execute(
        organization_id=actor.organization_id, agent_id=agent_id,
        action_type=payload.action_type, trigger="OPERATOR", reason=payload.reason,
        operator=actor, target_id=payload.target_id,
        threat_finding_id=payload.threat_finding_id, confirm=payload.confirm,
    )


@router.post("/containment/{action_id}/revert", response_model=ContainmentActionRead)
def revert_containment(
    action_id: uuid.UUID,
    actor: User = Depends(require_permission(_CONTAIN)),
    db: Session = Depends(get_db),
):
    """Reverse a reversible containment action through the same authority's
    own reverse operation. Never available for SUSPEND_AGENT/
    TERMINATE_EXECUTION (kill-switch dominance) or ISOLATE_CREDENTIAL (a
    revoked credential has no reverse)."""
    from app.identity.errors import ErrorCode, IdentityError

    action = db.get(ContainmentAction, action_id)
    if action is None or action.organization_id != actor.organization_id:
        raise IdentityError(ErrorCode.CONTAINMENT_ACTION_NOT_FOUND, "Containment action not found.")
    return ContainmentOrchestrator(db).revert(actor, action)
