"""Phase 5.5 (M5.5) - "shadow agents" as a **derived, disputable finding-state**.

There is no ``shadow`` column anywhere. An agent is shadow **iff** it has an
open finding whose ``rule_id`` is in ``app.posture.rules.SHADOW_RULE_IDS``
(discovered-outside-lifecycle, unmanaged-external-agent,
unowned-with-production-access, production-activity-without-governance). Each
condition names itself, carries its evidence, and clears when the underlying
finding is resolved or the condition stops holding on the next evaluation.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.posture import PostureFinding
from app.posture.rules import RULES_BY_ID, SHADOW_RULE_IDS


class ShadowAgentService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _open_shadow_findings(self, organization_id: uuid.UUID,
                              agent_id: uuid.UUID | None = None) -> list[PostureFinding]:
        stmt = select(PostureFinding).where(
            PostureFinding.organization_id == organization_id,
            PostureFinding.status.in_(("OPEN", "ACKNOWLEDGED")),
            PostureFinding.outcome == "FINDING",
            PostureFinding.rule_id.in_(tuple(SHADOW_RULE_IDS)),
        )
        if agent_id is not None:
            stmt = stmt.where(PostureFinding.subject_id == agent_id)
        return list(self.db.execute(stmt.order_by(PostureFinding.first_seen_at)).scalars())

    @staticmethod
    def _condition(f: PostureFinding) -> dict:
        rule = RULES_BY_ID.get(f.rule_id)
        return {
            "finding_id": str(f.id),
            "rule_id": f.rule_id,
            "control_id": f.control_id,
            "severity": f.severity,
            "status": f.status,
            "reason": f.reason,
            "evidence": f.evidence,
            "first_seen_at": f.first_seen_at.isoformat(),
            "summary": rule.summary if rule else None,
        }

    def list_shadow_agents(self, organization_id: uuid.UUID) -> list[dict]:
        findings = self._open_shadow_findings(organization_id)
        by_agent: dict[uuid.UUID, list[PostureFinding]] = {}
        for f in findings:
            by_agent.setdefault(f.subject_id, []).append(f)
        out: list[dict] = []
        for agent_id, fs in by_agent.items():
            agent = self.db.get(Agent, agent_id)
            out.append({
                "agent": {
                    "id": str(agent_id),
                    "name": agent.name if agent else None,
                    "control_state": agent.control_state if agent else None,
                    "origin_category": agent.origin_category if agent else None,
                },
                "shadow": True,
                "conditions": [self._condition(f) for f in fs],
                "note": (
                    "Derived from open shadow-class posture findings, not a stored flag. "
                    "Each condition is disputable and clears when its finding resolves."
                ),
            })
        return sorted(out, key=lambda e: e["agent"]["id"])

    def agent_shadow_state(self, organization_id: uuid.UUID, agent_id: uuid.UUID) -> dict:
        fs = self._open_shadow_findings(organization_id, agent_id)
        return {
            "agent_id": str(agent_id),
            "shadow": bool(fs),
            "conditions": [self._condition(f) for f in fs],
        }


__all__ = ["ShadowAgentService"]
