"""Phase 5.6 (M5.6) - ``ThreatEvaluator``: run the deterministic rule catalog
over an agent (or a whole tenant) and reconcile threat findings.

Mirrors ``app.posture.evaluator.PostureEvaluator`` closely — idempotent,
per-rule auto-resolution, fails open (a rule that raises produces no
finding). The one addition: a newly-opened or reopened **HIGH/CRITICAL**
finding creates a **RECOMMENDED** containment action (§8 of the build
prompt's flow) — a suggestion only, nothing invoked. This is the "bounded
automated" half of containment: detection can recommend, it never acts.
Only an explicit, confirmed call to ``ContainmentOrchestrator.execute``
(operator, or a future narrowly-scoped automation) invokes a real authority.

Off every enforcement path: nothing here calls ``KillSwitchService``,
``RuntimeGovernanceEngine``, or any revoke/disable method — recommending an
action is a row, not an act (AST-proven, ``test_ac04``).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.authorization.services import AuthorizationAuditService
from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.threat import ContainmentAction, ThreatFinding
from app.threat.lifecycle import ThreatFindingService
from app.threat.rules import RULES, THREAT_RULESET_VERSION, ThreatContext

logger = logging.getLogger(__name__)

_SKIP_LIFECYCLE = frozenset({"ARCHIVED", "RETIRED"})
_RECOMMEND_SEVERITIES = frozenset({"HIGH", "CRITICAL"})


@dataclass
class AgentEvaluation:
    agent_id: uuid.UUID
    opened: int = 0
    reopened: int = 0
    sustained: int = 0
    resolved: int = 0
    recommended: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class EvaluationSummary:
    organization_id: uuid.UUID
    agents_evaluated: int = 0
    findings_opened: int = 0
    findings_resolved: int = 0
    recommendations_created: int = 0
    rule_errors: int = 0
    ruleset_version: str = THREAT_RULESET_VERSION
    per_agent: list[AgentEvaluation] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "organization_id": str(self.organization_id),
            "agents_evaluated": self.agents_evaluated,
            "findings_opened": self.findings_opened,
            "findings_resolved": self.findings_resolved,
            "recommendations_created": self.recommendations_created,
            "rule_errors": self.rule_errors,
            "ruleset_version": self.ruleset_version,
        }


class ThreatEvaluator:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.lifecycle = ThreatFindingService(db)

    def evaluate_agent(self, actor, agent_id: uuid.UUID) -> EvaluationSummary:
        agent = self.db.get(Agent, agent_id)
        if agent is None or agent.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.THREAT_SUBJECT_NOT_FOUND, "No such agent in this organization.")
        summary = EvaluationSummary(organization_id=actor.organization_id)
        self._evaluate_one(actor.organization_id, agent, summary)
        self._audit_sweep(actor, summary, scope=f"agent:{agent_id}")
        return summary

    def evaluate_tenant(self, actor) -> EvaluationSummary:
        summary = EvaluationSummary(organization_id=actor.organization_id)
        agents = list(
            self.db.execute(
                select(Agent).where(Agent.organization_id == actor.organization_id)
            ).scalars()
        )
        for agent in agents:
            if agent.lifecycle_status in _SKIP_LIFECYCLE:
                continue
            self._evaluate_one(actor.organization_id, agent, summary)
        self._audit_sweep(actor, summary, scope="tenant")
        return summary

    def _evaluate_one(self, organization_id: uuid.UUID, agent: Agent,
                      summary: EvaluationSummary) -> None:
        ctx = ThreatContext(self.db, organization_id, agent)
        ev = AgentEvaluation(agent_id=agent.id)

        for rule in RULES:
            try:
                self._run_rule(organization_id, rule, agent, ctx, ev)
            except Exception as exc:  # noqa: BLE001 - one rule must not stop the sweep; fails open
                self.db.rollback()
                logger.warning("threat rule %s failed for agent %s: %s", rule.id, agent.id, exc)
                ev.errors.append(f"{rule.id}: {exc.__class__.__name__}")
                summary.rule_errors += 1

        summary.agents_evaluated += 1
        summary.findings_opened += ev.opened + ev.reopened
        summary.findings_resolved += ev.resolved
        summary.recommendations_created += ev.recommended
        summary.per_agent.append(ev)

    def _run_rule(self, organization_id: uuid.UUID, rule, agent: Agent,
                  ctx: ThreatContext, ev: AgentEvaluation) -> None:
        outcome = rule.evaluate(ctx, {})
        dedup_key = f"{rule.id}:AGENT:{agent.id}"

        if outcome.outcome == "CLEAR":
            resolved = self.lifecycle.auto_resolve(
                organization_id, dedup_key, "the rule evaluated and nothing suspicious is in the window")
            if resolved is not None:
                ev.resolved += 1
            return

        severity = outcome.severity or rule.severity
        before = self._status_of(organization_id, dedup_key)
        finding = self.lifecycle.raise_finding(
            organization_id=organization_id, rule_id=rule.id, rule_version=rule.version,
            ruleset_version=THREAT_RULESET_VERSION, severity=severity, agent_id=agent.id,
            reason=outcome.reason, evidence=outcome.evidence, attribution=outcome.attribution,
            dedup_key=dedup_key,
        )
        newly_active = before in (None, "RESOLVED")
        if before is None:
            ev.opened += 1
        elif before == "RESOLVED":
            ev.reopened += 1
        else:
            ev.sustained += 1

        if newly_active and severity in _RECOMMEND_SEVERITIES:
            self._recommend(organization_id, agent, finding, severity)
            ev.recommended += 1

    def _recommend(self, organization_id: uuid.UUID, agent: Agent, finding: ThreatFinding,
                   severity: str) -> None:
        """A RECOMMENDED containment action -- a suggestion, never an act. No
        authority is invoked here; ``authority_ref``/``result`` stay empty."""
        existing = self.db.execute(
            select(ContainmentAction.id).where(
                ContainmentAction.threat_finding_id == finding.id,
                ContainmentAction.status == "RECOMMENDED",
            ).limit(1)
        ).first()
        if existing is not None:
            return  # already recommended for this open finding
        action = ContainmentAction(
            organization_id=organization_id, action_type="SUSPEND_AGENT", authority="KILL_SWITCH",
            trigger="THREAT", automated=True, agent_id=agent.id, target_type=None, target_id=None,
            control_state_at_time=agent.control_state, status="RECOMMENDED",
            requires_confirmation=True, threat_finding_id=finding.id,
            reason=f"Recommended by threat rule {finding.rule_id} ({severity}): {finding.reason}",
        )
        self.db.add(action)
        AuthorizationAuditService(self.db).record_change(
            AuthorizationAuditEvent.CONTAINMENT_ACTION_RECOMMENDED,
            organization_id=organization_id, actor_id=None,
            meta={"threat_finding_id": str(finding.id), "action_type": action.action_type,
                  "agent_id": str(agent.id)},
        )
        self.db.commit()

    def _status_of(self, organization_id: uuid.UUID, dedup_key: str) -> str | None:
        row = self.db.execute(
            select(ThreatFinding.status).where(
                ThreatFinding.organization_id == organization_id,
                ThreatFinding.dedup_key == dedup_key,
            ).order_by(ThreatFinding.first_seen_at.desc()).limit(1)
        ).first()
        return row[0] if row else None

    def _audit_sweep(self, actor, summary: EvaluationSummary, *, scope: str) -> None:
        AuthorizationAuditService(self.db).record_change(
            AuthorizationAuditEvent.THREAT_EVALUATED,
            organization_id=actor.organization_id, actor_id=getattr(actor, "id", None),
            meta={"scope": scope, **summary.as_dict()},
        )
        self.db.commit()


__all__ = ["ThreatEvaluator", "EvaluationSummary", "AgentEvaluation"]
