"""Phase 5.5 (M5.5) - the security-posture HTTP surface, under ``/api/v1/posture``.

Read-and-triage only. **No route enforces anything** - reading a finding or a
score confers nothing, a lifecycle transition changes a finding's status and
audits it, and rule settings tune the (deterministic) engine. The 4.3
governance engine + kill switch remain the sole enforcers.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_permission
from app.models.agent import Agent
from app.models.posture import PostureFinding
from app.models.user import User
from app.posture.evaluator import PostureEvaluator
from app.posture.lifecycle import PostureFindingService
from app.posture.rules import SHADOW_RULE_IDS
from app.posture.schemas import (
    FindingRead,
    FindingTransition,
    RuleSettingRead,
    RuleSettingUpdate,
)
from app.posture.settings import PostureRuleSettingService
from app.posture.shadow import ShadowAgentService
from app.posture.summary import PostureSummaryService

router = APIRouter(prefix="/api/v1/posture", tags=["security-posture"])

_VIEW = "posture.view"
_MANAGE = "posture.manage"


def _require_agent(db: Session, actor: User, agent_id: uuid.UUID) -> Agent:
    from app.identity.errors import ErrorCode, IdentityError

    agent = db.get(Agent, agent_id)
    if agent is None or agent.organization_id != actor.organization_id:
        raise IdentityError(ErrorCode.POSTURE_SUBJECT_NOT_FOUND, "No such agent in this organization.")
    return agent


@router.get("/findings", response_model=list[FindingRead])
def list_findings(
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    rule_id: str | None = Query(default=None),
    subject_id: uuid.UUID | None = Query(default=None),
    outcome: str | None = Query(default=None),
    shadow: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    stmt = select(PostureFinding).where(PostureFinding.organization_id == actor.organization_id)
    if status:
        stmt = stmt.where(PostureFinding.status == status)
    if severity:
        stmt = stmt.where(PostureFinding.severity == severity)
    if rule_id:
        stmt = stmt.where(PostureFinding.rule_id == rule_id)
    if subject_id:
        stmt = stmt.where(PostureFinding.subject_id == subject_id)
    if outcome:
        stmt = stmt.where(PostureFinding.outcome == outcome)
    if shadow is True:
        stmt = stmt.where(PostureFinding.rule_id.in_(tuple(SHADOW_RULE_IDS)))
    elif shadow is False:
        stmt = stmt.where(PostureFinding.rule_id.notin_(tuple(SHADOW_RULE_IDS)))
    stmt = stmt.order_by(PostureFinding.severity.desc(), PostureFinding.first_seen_at.desc()).limit(limit)
    return list(db.execute(stmt).scalars())


@router.get("/findings/{finding_id}", response_model=FindingRead)
def get_finding(
    finding_id: uuid.UUID,
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    return PostureFindingService(db).get_or_404(actor, finding_id)


def _transition(db: Session, actor: User, finding_id: uuid.UUID, target: str,
                payload: FindingTransition) -> PostureFinding:
    svc = PostureFindingService(db)
    finding = svc.get_or_404(actor, finding_id)
    return svc.transition(finding, target, actor.id, note=payload.note)


@router.post("/findings/{finding_id}/acknowledge", response_model=FindingRead)
def acknowledge_finding(
    finding_id: uuid.UUID,
    payload: FindingTransition = FindingTransition(),
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
):
    return _transition(db, actor, finding_id, "ACKNOWLEDGED", payload)


@router.post("/findings/{finding_id}/resolve", response_model=FindingRead)
def resolve_finding(
    finding_id: uuid.UUID,
    payload: FindingTransition = FindingTransition(),
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
):
    return _transition(db, actor, finding_id, "RESOLVED", payload)


@router.post("/findings/{finding_id}/suppress", response_model=FindingRead)
def suppress_finding(
    finding_id: uuid.UUID,
    payload: FindingTransition = FindingTransition(),
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
):
    """Suppression is not resolution: a suppressed finding is not re-opened on
    recurrence (that is the point of suppressing it). Permissioned + audited."""
    return _transition(db, actor, finding_id, "SUPPRESSED", payload)


@router.get("/agents/{agent_id}/findings", response_model=list[FindingRead])
def agent_findings(
    agent_id: uuid.UUID,
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    _require_agent(db, actor, agent_id)
    return list(
        db.execute(
            select(PostureFinding)
            .where(
                PostureFinding.organization_id == actor.organization_id,
                PostureFinding.subject_id == agent_id,
            )
            .order_by(PostureFinding.status, PostureFinding.severity.desc(),
                      PostureFinding.first_seen_at.desc())
        ).scalars()
    )


@router.post("/agents/{agent_id}/evaluate")
def evaluate_agent(
    agent_id: uuid.UUID,
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    """Run the deterministic posture rule set for one agent. Idempotent."""
    _require_agent(db, actor, agent_id)
    return PostureEvaluator(db).evaluate_agent(actor, agent_id).as_dict()


@router.post("/evaluate")
def evaluate_tenant(
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    """Run the deterministic posture rule set for every non-archived agent in
    the tenant. The same work the ``posture.evaluate`` scheduler handler does."""
    return PostureEvaluator(db).evaluate_tenant(actor).as_dict()


@router.get("/shadow-agents")
def shadow_agents(
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
) -> dict:
    """"Shadow agents" - a query over open shadow-class posture findings, not a
    stored flag. Each agent lists the conditions that make it shadow."""
    agents = ShadowAgentService(db).list_shadow_agents(actor.organization_id)
    return {"shadow_rule_ids": sorted(SHADOW_RULE_IDS), "count": len(agents), "agents": agents}


@router.get("/agents/{agent_id}/shadow")
def agent_shadow(
    agent_id: uuid.UUID,
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
) -> dict:
    _require_agent(db, actor, agent_id)
    return ShadowAgentService(db).agent_shadow_state(actor.organization_id, agent_id)


@router.get("/summary")
def posture_summary(
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
) -> dict:
    """A deterministic, versioned, reconstructable posture aggregate - the
    formula, the weights, the ruleset version and the per-rule contributions
    are all in the response, so a CISO can see why the number is what it is."""
    return PostureSummaryService(db).summarize(actor.organization_id)


@router.get("/rules", response_model=list[RuleSettingRead])
def list_rules(
    actor: User = Depends(require_permission(_VIEW)),
    db: Session = Depends(get_db),
):
    return PostureRuleSettingService(db).describe(actor.organization_id)


@router.put("/rules/{rule_id}", response_model=RuleSettingRead)
def update_rule(
    rule_id: str,
    payload: RuleSettingUpdate,
    actor: User = Depends(require_permission(_MANAGE)),
    db: Session = Depends(get_db),
):
    """Enable/disable a rule or override its parameters for this organization.
    Versioned (monotonic ``revision``) and audited - so a posture score stays
    reconstructable and a threshold change is explainable."""
    svc = PostureRuleSettingService(db)
    svc.update(actor, rule_id, enabled=payload.enabled, params=payload.params)
    return next(r for r in svc.describe(actor.organization_id) if r["rule_id"] == rule_id)
