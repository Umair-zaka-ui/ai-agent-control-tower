"""Phase 5.5 (M5.5) - ``PostureEvaluator``: run the deterministic rule
catalog over an agent (or a whole tenant) and reconcile the findings.

**Idempotent** - re-running over unchanged evidence yields the same open
findings (the DB-enforced dedup key does the work; a still-true condition
bumps ``recurrence_count`` and nothing else). **3.8-schedulable** - the
``posture.evaluate`` handler (``app.scheduler.handlers``) calls
``evaluate_tenant``; there is no new scheduler.

**Reconciliation, per rule.** After a rule runs for an agent, any open
finding for that (rule, agent) whose condition the rule did *not* re-assert
is auto-resolved. A rule that returns ``INSUFFICIENT_DATA`` leaves a prior
finding open (unknown != safe) and records the gap explicitly.

**Off every execution path** - nothing here writes an execution status,
raises a governance exception or reaches the kill switch (AST-proven,
``test_ac07``). A rule that raises is caught: the sweep produces no finding
for that rule, fabricates nothing, and never blocks anything.
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
from app.models.posture import PostureFinding
from app.posture.lifecycle import PostureFindingService
from app.posture.rules import RULES, POSTURE_RULESET_VERSION, PostureContext, PostureRule
from app.posture.settings import PostureRuleSettingService

logger = logging.getLogger(__name__)

# Agents in these lifecycle states are not evaluated - a retired/archived
# agent's posture is not actionable, and its stale evidence would only produce
# noise.
_SKIP_LIFECYCLE = frozenset({"ARCHIVED", "RETIRED"})


@dataclass
class AgentEvaluation:
    agent_id: uuid.UUID
    opened: int = 0
    reopened: int = 0
    sustained: int = 0
    resolved: int = 0
    insufficient_data: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class EvaluationSummary:
    organization_id: uuid.UUID
    agents_evaluated: int = 0
    findings_opened: int = 0
    findings_resolved: int = 0
    insufficient_data: int = 0
    rule_errors: int = 0
    ruleset_version: str = POSTURE_RULESET_VERSION
    per_agent: list[AgentEvaluation] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "organization_id": str(self.organization_id),
            "agents_evaluated": self.agents_evaluated,
            "findings_opened": self.findings_opened,
            "findings_resolved": self.findings_resolved,
            "insufficient_data": self.insufficient_data,
            "rule_errors": self.rule_errors,
            "ruleset_version": self.ruleset_version,
        }


class PostureEvaluator:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.lifecycle = PostureFindingService(db)
        self.settings = PostureRuleSettingService(db)

    # ------------------------------------------------------------------ #
    def evaluate_agent(self, actor, agent_id: uuid.UUID) -> EvaluationSummary:
        agent = self.db.get(Agent, agent_id)
        if agent is None or agent.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.POSTURE_SUBJECT_NOT_FOUND, "No such agent in this organization.")
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

    # ------------------------------------------------------------------ #
    def _evaluate_one(self, organization_id: uuid.UUID, agent: Agent,
                      summary: EvaluationSummary) -> None:
        ctx = PostureContext(self.db, organization_id, agent)
        ev = AgentEvaluation(agent_id=agent.id)
        effective = self.settings.effective(organization_id)

        for rule in RULES:
            cfg = effective.get(rule.id, {"enabled": True, "params": {}, "revision": 0})
            try:
                if not cfg["enabled"]:
                    self._resolve_disabled(organization_id, rule, agent, ev)
                    continue
                self._run_rule(organization_id, rule, agent, ctx, cfg, ev)
            except Exception as exc:  # noqa: BLE001 - one rule must not stop the sweep; fail open
                self.db.rollback()
                logger.warning("posture rule %s failed for agent %s: %s", rule.id, agent.id, exc)
                ev.errors.append(f"{rule.id}: {exc.__class__.__name__}")
                summary.rule_errors += 1

        summary.agents_evaluated += 1
        summary.findings_opened += ev.opened + ev.reopened
        summary.findings_resolved += ev.resolved
        summary.insufficient_data += ev.insufficient_data
        summary.per_agent.append(ev)

    def _run_rule(self, organization_id: uuid.UUID, rule: PostureRule, agent: Agent,
                  ctx: PostureContext, cfg: dict, ev: AgentEvaluation) -> None:
        outcomes = rule.evaluate(ctx, cfg["params"])
        base = f"{rule.id}:AGENT:{agent.id}"
        governing = {
            "ruleset_version": POSTURE_RULESET_VERSION,
            "rule_version": rule.version,
            "params": {**rule.default_params, **cfg["params"]},
            "settings_revision": cfg["revision"],
        }
        produced_finding_keys: set[str] = set()
        produced_insufficient = False

        for o in outcomes:
            if o.outcome == "FINDING":
                key = base if o.dedup_suffix is None else f"{base}:{o.dedup_suffix}"
                produced_finding_keys.add(key)
                before = self._status_of(organization_id, key)
                finding = self.lifecycle.raise_finding(
                    organization_id=organization_id, rule_id=rule.id, control_id=rule.control_id,
                    rule_version=rule.version, ruleset_version=POSTURE_RULESET_VERSION,
                    outcome="FINDING", severity=o.severity or rule.severity,
                    subject_type="AGENT", subject_id=agent.id,
                    reason=o.reason, remediation=o.remediation, evidence=o.evidence,
                    governing_policy=governing, dedup_key=key,
                )
                if before is None:
                    ev.opened += 1
                elif before == "RESOLVED":
                    ev.reopened += 1
                else:
                    ev.sustained += 1
            elif o.outcome == "INSUFFICIENT_DATA":
                produced_insufficient = True
                key = f"insufficient:{base}"
                self.lifecycle.raise_finding(
                    organization_id=organization_id, rule_id=rule.id, control_id=rule.control_id,
                    rule_version=rule.version, ruleset_version=POSTURE_RULESET_VERSION,
                    outcome="INSUFFICIENT_DATA", severity="INFO",
                    subject_type="AGENT", subject_id=agent.id,
                    reason=o.reason, remediation=o.remediation
                    or "Provide the missing evidence, then re-evaluate.",
                    evidence=o.evidence, governing_policy=governing, dedup_key=key,
                )
                ev.insufficient_data += 1
            # CLEAR: nothing to open; reconciliation below closes stale findings

        # reconcile: close any open finding for this (rule, agent) that the
        # rule did not re-assert this run. A rule that returned
        # INSUFFICIENT_DATA "cannot tell" -- it never auto-resolves a prior
        # FINDING (unknown != safe); it only clears a superseded insufficient
        # marker.
        for stale_key in self._open_keys_for_rule(organization_id, rule.id, agent.id):
            is_insufficient_marker = stale_key == f"insufficient:{base}"
            if is_insufficient_marker:
                if produced_insufficient:
                    continue
                reason = "the rule can now evaluate; the data gap is closed"
            else:
                if produced_insufficient or stale_key in produced_finding_keys:
                    continue
                reason = "the rule evaluated and the condition no longer holds"
            resolved = self.lifecycle.auto_resolve(organization_id, stale_key, reason)
            if resolved is not None:
                ev.resolved += 1

    def _resolve_disabled(self, organization_id: uuid.UUID, rule: PostureRule,
                          agent: Agent, ev: AgentEvaluation) -> None:
        for key in self._open_keys_for_rule(organization_id, rule.id, agent.id):
            resolved = self.lifecycle.auto_resolve(
                organization_id, key, f"posture rule {rule.id} is disabled for this organization"
            )
            if resolved is not None:
                ev.resolved += 1

    # ------------------------------------------------------------------ #
    def _status_of(self, organization_id: uuid.UUID, dedup_key: str) -> str | None:
        row = self.db.execute(
            select(PostureFinding.status).where(
                PostureFinding.organization_id == organization_id,
                PostureFinding.dedup_key == dedup_key,
            ).order_by(PostureFinding.first_seen_at.desc()).limit(1)
        ).first()
        return row[0] if row else None

    def _open_keys_for_rule(self, organization_id: uuid.UUID, rule_id: str,
                            agent_id: uuid.UUID) -> list[str]:
        return list(
            self.db.execute(
                select(PostureFinding.dedup_key).where(
                    PostureFinding.organization_id == organization_id,
                    PostureFinding.rule_id == rule_id,
                    PostureFinding.subject_id == agent_id,
                    PostureFinding.status.in_(("OPEN", "ACKNOWLEDGED")),
                )
            ).scalars()
        )

    def _audit_sweep(self, actor, summary: EvaluationSummary, *, scope: str) -> None:
        AuthorizationAuditService(self.db).record_change(
            AuthorizationAuditEvent.POSTURE_EVALUATED,
            organization_id=actor.organization_id,
            actor_id=getattr(actor, "id", None),
            meta={"scope": scope, **summary.as_dict()},
        )
        self.db.commit()


__all__ = ["PostureEvaluator", "EvaluationSummary", "AgentEvaluation"]
