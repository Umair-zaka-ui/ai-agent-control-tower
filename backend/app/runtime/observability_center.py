"""Phase 4.9 -- read models for the Enterprise Runtime Governance &
Observability Center (ACT-SRS-M4 §4.9, §28, §29).

**Everything here is read-only, and that is the phase's central constraint** --
the same discipline ``app.runtime.operations`` was built with for Milestone 3's
Release Operations Center. Phases 4.1-4.8 own every rule: the trace assembler,
the governance engine, the cost aggregator, the behavioral engine, the SLO
evaluator, the alert lifecycle, the capture-policy resolver. This module
computes no domain state, decides nothing, writes nothing. It reads what those
engines already produced and *shapes* it for a screen.

Enforced structurally, not just promised: nothing here imports a service that
mutates, and a test asserts no ``add`` / ``commit`` / ``delete`` / ``flush``
call appears anywhere in it.

**Why these two read models exist**, when the rule is "reuse the existing
endpoints":

- ``overview`` -- the Runtime Overview screen needs the fleet picture in one
  request: execution volume and success rate over 24h, spend today, open alerts
  by severity, worker health, SLO breach count, recent behavioral anomalies, and
  the org's effective capture posture. Composing that client-side is seven
  requests to render one screen, and it renders in an inconsistent half-state as
  each lands. (Exporter health is *not* in this composite -- it belongs to the
  4.6 OpenTelemetry export plane that ``app/runtime`` never imports; the screen
  fetches it from ``GET /observability/export/health`` directly.)
- ``governance_decisions`` -- genuinely missing. Phase 4.3 exposed the decision
  lineage *per execution* (``GET /executions/{id}/governance-decisions``);
  there is no way to answer "show me every STOP this week" without knowing
  every execution id in advance. The Governance Decisions view needs a
  tenant-wide, filterable list.

**Content is never read here.** The Trace Detail *content* pane is served by
4.8's ``GET /observability/traces/{trace_id}/content`` -- with its distinct
``runtime.trace.content.view`` permission and its ``RUNTIME_TRACE_CONTENT_VIEWED``
audit. This module adds no content route and reads no content column; a
``reason`` string on a governance decision is a platform-templated sentence
(a ceiling, a tool name, a model name), never a prompt or model output.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.runtime import (
    AgentExecution,
    BehavioralFinding,
    RuntimeAlert,
    RuntimeGovernanceDecision,
    SLODefinition,
    SLOEvaluation,
)
from app.models.user import User

#: Execution statuses that count as terminal for the overview success rate --
#: identical to 3.5's / 4.5's / 4.7's ``TERMINAL`` set (a test asserts it).
_TERMINAL = frozenset({
    "SUCCEEDED", "FAILED", "TIMED_OUT", "DEAD_LETTERED", "DENIED", "BLOCKED", "CANCELLED",
})
_ACTIVE_ALERT = ("OPEN", "ACKNOWLEDGED")
_GOVERNANCE_DECISIONS = frozenset({"ALLOW", "DENY", "CHALLENGE", "STOP"})
#: The six checkpoints the 4.3 engine can produce -- identical to migration
#: 0047's CHECK constraint on ``runtime_governance_decisions.checkpoint``.
_GOVERNANCE_CHECKPOINTS = frozenset({
    "BEFORE_FIRST_MODEL_CALL", "AFTER_MODEL_RESPONSE", "BEFORE_TOOL_EXECUTION",
    "AFTER_TOOL_EXECUTION", "BEFORE_NEXT_ITERATION", "BEFORE_FINAL_OUTPUT",
})


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ObservabilityCenterReadModel:
    """Read-only aggregation for the 4.9 operator center. Holds a ``Session``
    but never adds, deletes, commits or flushes through it."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Runtime Overview (M4-4.9-FR-001)
    # ------------------------------------------------------------------ #
    def overview(self, actor: User) -> dict:
        org = actor.organization_id
        now = _now()
        day_ago = now - timedelta(hours=24)
        week_ago = now - timedelta(days=7)

        return {
            "generated_at": now.isoformat(),
            "executions": self._execution_stats(org, day_ago),
            "spend": self._spend_today(org, now),
            "alerts": self._alert_stats(org),
            "slos": self._slo_stats(org),
            "behavior": self._behavior_stats(org, week_ago),
            "workers": self._worker_stats(actor),
            "capture": self._capture_posture(org),
        }

    def _execution_stats(self, org: uuid.UUID, since: datetime) -> dict:
        rows = self.db.execute(
            select(AgentExecution.status, func.count(AgentExecution.id))
            .where(AgentExecution.organization_id == org,
                   AgentExecution.created_at >= since)
            .group_by(AgentExecution.status)
        ).all()
        by_status = {status: count for status, count in rows}
        terminal = sum(c for s, c in by_status.items() if s in _TERMINAL)
        succeeded = by_status.get("SUCCEEDED", 0)
        failed = sum(by_status.get(s, 0) for s in ("FAILED", "TIMED_OUT", "DEAD_LETTERED"))
        running = self.db.execute(
            select(func.count(AgentExecution.id)).where(
                AgentExecution.organization_id == org,
                AgentExecution.status.in_(("RUNNING", "WAITING_FOR_TOOL", "RETRYING")))
        ).scalar_one()
        queued = self.db.execute(
            select(func.count(AgentExecution.id)).where(
                AgentExecution.organization_id == org,
                AgentExecution.status.in_(("QUEUED", "SCHEDULED")))
        ).scalar_one()
        # success_rate is None (not 0) below the sufficiency floor -- "no data"
        # is not "0% healthy" (the 3.5/4.5/4.7 discipline).
        success_rate = round(succeeded / terminal, 4) if terminal >= 20 else None
        return {
            "window_hours": 24,
            "by_status": by_status,
            "terminal": terminal,
            "succeeded": succeeded,
            "failed_24h": failed,
            "running_now": running,
            "queued_now": queued,
            "success_rate": success_rate,
            "success_rate_insufficient_data": success_rate is None,
        }

    def _spend_today(self, org: uuid.UUID, now: datetime) -> dict:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        total = self.db.execute(
            select(func.coalesce(func.sum(AgentExecution.cost_amount), 0))
            .where(AgentExecution.organization_id == org,
                   AgentExecution.created_at >= start)
        ).scalar_one()
        estimated = self.db.execute(
            select(func.count(AgentExecution.id))
            .where(AgentExecution.organization_id == org,
                   AgentExecution.created_at >= start,
                   AgentExecution.cost_is_estimated.is_(True))
        ).scalar_one()
        return {
            "since": start.isoformat(),
            "amount": float(total or 0),
            "currency": "USD",
            "includes_estimated": estimated > 0,
            "estimated_row_count": estimated,
        }

    def _alert_stats(self, org: uuid.UUID) -> dict:
        rows = self.db.execute(
            select(RuntimeAlert.severity, func.count(RuntimeAlert.id))
            .where(RuntimeAlert.organization_id == org,
                   RuntimeAlert.status.in_(_ACTIVE_ALERT))
            .group_by(RuntimeAlert.severity)
        ).all()
        by_severity = {sev: count for sev, count in rows}
        return {
            "active": sum(by_severity.values()),
            "by_severity": by_severity,
            "critical": by_severity.get("CRITICAL", 0),
        }

    def _slo_stats(self, org: uuid.UUID) -> dict:
        enabled = self.db.execute(
            select(func.count(SLODefinition.id))
            .where(SLODefinition.organization_id == org, SLODefinition.enabled.is_(True))
        ).scalar_one()
        # The latest evaluation per SLO, and how many are BREACHED.
        latest = (
            select(SLOEvaluation.slo_id,
                   func.max(SLOEvaluation.evaluated_at).label("latest"))
            .where(SLOEvaluation.organization_id == org)
            .group_by(SLOEvaluation.slo_id)
            .subquery()
        )
        states = self.db.execute(
            select(SLOEvaluation.state, func.count(SLOEvaluation.id))
            .join(latest, (SLOEvaluation.slo_id == latest.c.slo_id)
                  & (SLOEvaluation.evaluated_at == latest.c.latest))
            .group_by(SLOEvaluation.state)
        ).all()
        by_state = {state: count for state, count in states}
        return {
            "enabled": enabled,
            "latest_by_state": by_state,
            "breached": by_state.get("BREACHED", 0),
            "insufficient_data": by_state.get("INSUFFICIENT_DATA", 0),
        }

    def _behavior_stats(self, org: uuid.UUID, since: datetime) -> dict:
        rows = self.db.execute(
            select(BehavioralFinding.state, func.count(BehavioralFinding.id))
            .where(BehavioralFinding.organization_id == org,
                   BehavioralFinding.evaluated_at >= since)
            .group_by(BehavioralFinding.state)
        ).all()
        by_state = {state: count for state, count in rows}
        return {
            "window_days": 7,
            "by_state": by_state,
            "anomalous": by_state.get("ANOMALOUS", 0),
            "degraded": by_state.get("DEGRADED", 0),
        }

    def _worker_stats(self, actor: User) -> dict:
        from app.runtime.services import HealthMonitoringService

        workers = HealthMonitoringService(self.db).workers(actor)
        by_status: dict[str, int] = {}
        for w in workers:
            by_status[w["status"]] = by_status.get(w["status"], 0) + 1
        return {
            "total": len(workers),
            "by_status": by_status,
            "offline": by_status.get("OFFLINE", 0),
            "degraded": by_status.get("DEGRADED", 0),
            "note": (
                "This environment runs an inline synchronous worker that does not "
                "heartbeat; an empty fleet here is expected, not an incident."
                if not workers else None
            ),
        }

    # Exporter health is deliberately NOT read here. It belongs to the
    # OpenTelemetry export plane (Phase 4.6), which `app/runtime` never imports --
    # a structural invariant a 4.6 test enforces (ruling #13/#14, ADR-0011).
    # The Runtime Overview screen fetches it from the existing
    # `GET /api/v1/observability/export/health` endpoint directly.

    def _capture_posture(self, org: uuid.UUID) -> dict:
        from app.telemetry_privacy.policy import resolve_capture_mode

        effective = resolve_capture_mode(self.db, organization_id=org)
        return {
            "org_effective_mode": effective.mode.value,
            "source": effective.source,
            "reason": effective.reason,
        }

    # ------------------------------------------------------------------ #
    # Governance Decisions (M4-4.9-FR-005)
    # ------------------------------------------------------------------ #
    def governance_decisions(
        self, actor: User, *, decision: str | None = None,
        checkpoint: str | None = None, agent_id: uuid.UUID | None = None,
        reason_code: str | None = None, since: datetime | None = None,
        limit: int = 50, offset: int = 0,
    ) -> dict:
        org = actor.organization_id
        stmt = (
            select(RuntimeGovernanceDecision, AgentExecution.agent_id, Agent.name)
            .join(AgentExecution,
                  AgentExecution.id == RuntimeGovernanceDecision.execution_id)
            .join(Agent, Agent.id == AgentExecution.agent_id, isouter=True)
            .where(RuntimeGovernanceDecision.organization_id == org)
        )
        if decision:
            stmt = stmt.where(RuntimeGovernanceDecision.decision == decision)
        if checkpoint:
            stmt = stmt.where(RuntimeGovernanceDecision.checkpoint == checkpoint)
        if agent_id:
            stmt = stmt.where(AgentExecution.agent_id == agent_id)
        if reason_code:
            stmt = stmt.where(RuntimeGovernanceDecision.reason_code == reason_code)
        if since:
            stmt = stmt.where(RuntimeGovernanceDecision.evaluated_at >= since)

        rows = self.db.execute(
            stmt.order_by(RuntimeGovernanceDecision.evaluated_at.desc(),
                          RuntimeGovernanceDecision.id.desc())
            .limit(min(max(limit, 1), 200) + 1).offset(max(offset, 0))
        ).all()
        has_more = len(rows) > min(max(limit, 1), 200)
        items = [self._decision_row(d, aid, name) for d, aid, name in rows[:limit]]
        return {
            "items": items,
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
            "vocabulary": {
                "decisions": sorted(_GOVERNANCE_DECISIONS),
                "checkpoints": sorted(_GOVERNANCE_CHECKPOINTS),
            },
        }

    @staticmethod
    def _decision_row(d: RuntimeGovernanceDecision, agent_id, agent_name) -> dict:
        return {
            "id": str(d.id),
            "execution_id": str(d.execution_id),
            "trace_id": d.trace_id,
            "agent_id": str(agent_id) if agent_id else None,
            "agent_name": agent_name,
            "checkpoint": d.checkpoint,
            "decision": d.decision,
            "reason_code": d.reason_code,
            # A platform-templated sentence -- never a prompt or model output.
            "reason": d.reason,
            "obligation": d.obligation,
            "policy_id": str(d.policy_id) if d.policy_id else None,
            "budget_id": str(d.budget_id) if d.budget_id else None,
            "evaluated_at": d.evaluated_at.isoformat() if d.evaluated_at else None,
        }
