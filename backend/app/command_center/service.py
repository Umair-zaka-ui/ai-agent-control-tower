"""Phase 5.8 (M5.8) - the Enterprise Agent Command Center's **read-model
aggregation**. Two things live here and nothing else: counts, and a paginated
inventory row.

**This module decides nothing.** It owns no domain state, no enforcement, no
rule and no score. Where a number already has an authority, it *calls* that
authority rather than recomputing it:

  * the posture score and its per-rule contributions come from
    ``PostureSummaryService`` (5.5) - this module never re-derives a weight;
  * "is this agent shadow, and why" comes from ``ShadowAgentService`` (5.5) -
    shadow stays a derived, explainable finding, never a flag invented here;
  * an agent's **enforcement mode and reach** come from ``app.bridge.modes``
    (5.7) - ``effective_mode``/``REACH``, the same functions the bridge itself
    uses. This is the single most important reuse in the phase: the command
    center must not have a second opinion about what ACT can do to an agent.

Everything else is a ``COUNT``/``GROUP BY`` over rows that already exist. An
aggregate of authoritative rows is not a new authority.

**Why this exists at all.** ``GET /runtime/agents`` is paginated at 500 rows
with no ``control_state``/``origin_category`` filter and no counts, so an
estate overview built on it would page through tens of thousands of rows and
count them in React - business logic in the browser, and unscalable. And an
inventory row needs each agent's enforcement mode, which would otherwise be one
extra request per row. Both are read-only aggregation, which is exactly the
narrow addition Phase 4.9 made for the same reason.

**Permission-truthful sections.** The estate spans domains that each have their
own permission (``posture.view``, ``threat.view``, ``external_governance.view``
...). A caller holding only ``agent.view`` must not be shown posture counts -
but must also not be shown **zero**, which would read as "no findings" when the
truth is "you cannot see them". Every optional section is therefore either
populated or ``None`` with a ``denied`` reason, and the UI renders the
difference. Reporting zero here would be the §10 fabrication rule broken in the
one direction nobody notices.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.authorization.middleware.gateway import AuthorizationGateway
from app.models.agent import Agent
from app.models.user import User

#: How far back "recent activity" looks for the estate's boundary-call and
#: containment counts. A window, not a lifetime total, because an operator
#: reading the estate cares what is happening now.
RECENT_WINDOW_HOURS = 24

#: An agent with no observation and no execution in this long is reported
#: dormant. It is a *reported* observation, never an enforced state.
DORMANT_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Section:
    """One optional estate section, and whether the caller may see it.

    ``denied`` is not an error: it is the truthful answer to "what is the
    posture of my estate" for someone who cannot read posture. It is carried
    separately from the data so the UI can never mistake it for a zero."""

    permission: str
    allowed: bool
    data: dict | None

    def as_payload(self) -> dict:
        if not self.allowed:
            return {"visible": False, "permission": self.permission, "data": None}
        return {"visible": True, "permission": self.permission, "data": self.data}


class CommandCenterService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    def _may(self, actor: User, permission: str) -> bool:
        """A soft, read-only permission probe for an optional section.

        It goes through the real ``AuthorizationGateway`` - the command center
        does not get its own opinion about permissions any more than it gets
        one about enforcement. ``record_decision=False`` because this is a
        rendering question asked several times per page load, not an access
        event; the decisions that matter are recorded when the operator
        actually triggers something.
        """
        return AuthorizationGateway(self.db).authorize(
            actor, permission, source="API", record_decision=False, audit_events=False,
        ).allowed

    # ------------------------------------------------------------------ #
    # Estate overview
    # ------------------------------------------------------------------ #
    def estate(self, actor: User) -> dict:
        org = actor.organization_id
        payload: dict = {
            "generated_at": _now().isoformat(),
            "agents": self._agent_counts(org),
            "posture": self._posture_section(actor, org).as_payload(),
            "shadow": self._shadow_section(actor, org).as_payload(),
            "threats": self._threat_section(actor, org).as_payload(),
            "external": self._external_section(actor, org).as_payload(),
            "graph": self._graph_section(actor, org).as_payload(),
            "cost": self._cost_section(actor, org).as_payload(),
        }
        return payload

    def _agent_counts(self, org: uuid.UUID) -> dict:
        """Plain aggregates over ``agents``. The one section always visible,
        because ``agent.view`` already gated the request."""
        from app.bridge.modes import NATIVE_CONTROL_STATE, effective_mode

        by_control = dict(self.db.execute(
            select(Agent.control_state, func.count())
            .where(Agent.organization_id == org)
            .group_by(Agent.control_state)
        ).all())
        by_origin = dict(self.db.execute(
            select(Agent.origin_category, func.count())
            .where(Agent.organization_id == org)
            .group_by(Agent.origin_category)
        ).all())
        # The enforcement mode is derived, so it is grouped by the two columns
        # it derives from rather than read off a column that does not exist.
        by_mode: dict[str, int] = {}
        rows = self.db.execute(
            select(Agent.control_state, Agent.external_enforcement_mode, func.count())
            .where(Agent.organization_id == org)
            .group_by(Agent.control_state, Agent.external_enforcement_mode)
        ).all()
        for control_state, external_mode, count in rows:
            stub = _ModeStub(control_state=control_state, external_enforcement_mode=external_mode)
            by_mode[effective_mode(stub)] = by_mode.get(effective_mode(stub), 0) + count

        total = sum(by_control.values())
        governed = by_control.get(NATIVE_CONTROL_STATE, 0)
        unowned = self.db.execute(
            select(func.count()).select_from(Agent).where(
                Agent.organization_id == org, Agent.owner_id.is_(None))
        ).scalar() or 0
        critical = self.db.execute(
            select(func.count()).select_from(Agent).where(
                Agent.organization_id == org, Agent.criticality == "CRITICAL")
        ).scalar() or 0
        dormant_before = _now() - timedelta(days=DORMANT_DAYS)
        dormant = self.db.execute(
            select(func.count()).select_from(Agent).where(
                Agent.organization_id == org,
                or_(Agent.last_observed_at.is_(None), Agent.last_observed_at < dormant_before),
                Agent.control_state != NATIVE_CONTROL_STATE,
            )
        ).scalar() or 0

        return {
            "total": total,
            "by_control_state": by_control,
            "by_origin_category": by_origin,
            "by_enforcement_mode": by_mode,
            "governed": governed,
            # Not a judgement -- literally "ACT does not run these".
            "ungoverned": total - governed,
            "unowned": unowned,
            "critical": critical,
            "dormant": dormant,
            "dormant_days": DORMANT_DAYS,
        }

    def _posture_section(self, actor: User, org: uuid.UUID) -> Section:
        if not self._may(actor, "posture.view"):
            return Section("posture.view", False, None)
        from app.posture.summary import PostureSummaryService

        # The score, the formula, the weights and the per-rule contributions
        # all come from 5.5 verbatim. This module adds no arithmetic.
        return Section("posture.view", True, PostureSummaryService(self.db).summarize(org))

    def _shadow_section(self, actor: User, org: uuid.UUID) -> Section:
        if not self._may(actor, "posture.view"):
            return Section("posture.view", False, None)
        from app.posture.rules import SHADOW_RULE_IDS
        from app.posture.shadow import ShadowAgentService

        agents = ShadowAgentService(self.db).list_shadow_agents(org)
        return Section("posture.view", True, {
            "count": len(agents),
            "shadow_rule_ids": sorted(SHADOW_RULE_IDS),
        })

    def _threat_section(self, actor: User, org: uuid.UUID) -> Section:
        if not self._may(actor, "threat.view"):
            return Section("threat.view", False, None)
        from app.models.threat import ContainmentAction, ThreatFinding

        by_severity = dict(self.db.execute(
            select(ThreatFinding.severity, func.count()).where(
                ThreatFinding.organization_id == org, ThreatFinding.status == "OPEN")
            .group_by(ThreatFinding.severity)
        ).all())
        since = _now() - timedelta(hours=RECENT_WINDOW_HOURS)
        by_status = dict(self.db.execute(
            select(ContainmentAction.status, func.count()).where(
                ContainmentAction.organization_id == org,
                ContainmentAction.created_at >= since)
            .group_by(ContainmentAction.status)
        ).all())
        return Section("threat.view", True, {
            "open_findings": sum(by_severity.values()),
            "open_by_severity": by_severity,
            "containment_window_hours": RECENT_WINDOW_HOURS,
            "containment_by_status": by_status,
            # REFUSED is surfaced on purpose: a containment ACT truthfully
            # could not perform is exactly what an operator needs to see.
            "containment_refused": by_status.get("REFUSED", 0),
        })

    def _external_section(self, actor: User, org: uuid.UUID) -> Section:
        if not self._may(actor, "external_governance.view"):
            return Section("external_governance.view", False, None)
        from app.models.bridge import ExternalCapabilityGrant, ExternalGatewayCall

        active_grants = self.db.execute(
            select(func.count()).select_from(ExternalCapabilityGrant).where(
                ExternalCapabilityGrant.organization_id == org,
                ExternalCapabilityGrant.revoked_at.is_(None))
        ).scalar() or 0
        since = _now() - timedelta(hours=RECENT_WINDOW_HOURS)
        by_outcome = dict(self.db.execute(
            select(ExternalGatewayCall.outcome, func.count()).where(
                ExternalGatewayCall.organization_id == org,
                ExternalGatewayCall.created_at >= since)
            .group_by(ExternalGatewayCall.outcome)
        ).all())
        return Section("external_governance.view", True, {
            "active_grants": active_grants,
            "window_hours": RECENT_WINDOW_HOURS,
            "boundary_calls_by_outcome": by_outcome,
            "boundary_calls_denied": by_outcome.get("DENIED", 0),
        })

    def _graph_section(self, actor: User, org: uuid.UUID) -> Section:
        if not self._may(actor, "graph.view"):
            return Section("graph.view", False, None)
        from app.models.graph import ControlGraphEdge, McpServer

        mcp_by_trust = dict(self.db.execute(
            select(McpServer.trust_status, func.count()).where(
                McpServer.organization_id == org).group_by(McpServer.trust_status)
        ).all())
        edges = self.db.execute(
            select(func.count()).select_from(ControlGraphEdge).where(
                ControlGraphEdge.organization_id == org,
                ControlGraphEdge.revoked_at.is_(None))
        ).scalar() or 0
        return Section("graph.view", True, {
            "mcp_servers": sum(mcp_by_trust.values()),
            "mcp_by_trust_status": mcp_by_trust,
            "active_edges": edges,
        })

    def _cost_section(self, actor: User, org: uuid.UUID) -> Section:
        """Cost is reported honestly or not at all.

        Phase 4.4 prices what it can measure; Phase 5.7 established that a
        boundary call ACT cannot price is recorded ``NOT_MEASURABLE`` rather
        than given an invented number. The estate carries that through: it
        reports how many budgets apply and how many recent boundary calls were
        unpriceable, and never sums a figure it does not have.
        """
        if not self._may(actor, "runtime.cost.view"):
            return Section("runtime.cost.view", False, None)
        from app.models.bridge import ExternalGatewayCall
        from app.models.runtime import Budget

        budgets = self.db.execute(
            select(func.count()).select_from(Budget).where(
                Budget.organization_id == org, Budget.enabled.is_(True))
        ).scalar() or 0
        since = _now() - timedelta(hours=RECENT_WINDOW_HOURS)
        not_measurable = self.db.execute(
            select(func.count()).select_from(ExternalGatewayCall).where(
                ExternalGatewayCall.organization_id == org,
                ExternalGatewayCall.created_at >= since,
                ExternalGatewayCall.cost_outcome == "NOT_MEASURABLE")
        ).scalar() or 0
        return Section("runtime.cost.view", True, {
            "enabled_budgets": budgets,
            "window_hours": RECENT_WINDOW_HOURS,
            "boundary_calls_not_measurable": not_measurable,
            "note": (
                "Boundary calls ACT cannot price are counted, not estimated. "
                "A cost ACT does not have is reported as unmeasurable, never as zero."
            ),
        })

    # ------------------------------------------------------------------ #
    # Inventory
    # ------------------------------------------------------------------ #
    def inventory(self, actor: User, *, control_state: str | None = None,
                  origin_category: str | None = None, enforcement_mode: str | None = None,
                  shadow_only: bool = False, query: str | None = None,
                  page: int = 1, page_size: int = 50) -> dict:
        """One page of agents, each already carrying the truthful affordance
        signal so the UI never has to ask per row (and never has to guess).

        ``enforcement_mode`` filters on a *derived* value, so it is applied
        after the mode is computed for the page rather than pushed into SQL as
        a column that does not exist. That keeps one definition of the mode -
        5.7's - instead of a second one spelled in a WHERE clause.
        """
        from app.bridge.modes import REACH, effective_mode

        stmt: Select = select(Agent).where(Agent.organization_id == actor.organization_id)
        if control_state:
            stmt = stmt.where(Agent.control_state == control_state)
        if origin_category:
            stmt = stmt.where(Agent.origin_category == origin_category)
        if query:
            stmt = stmt.where(Agent.name.ilike(f"%{query}%"))

        total = self.db.execute(
            select(func.count()).select_from(stmt.subquery())).scalar() or 0
        rows = list(self.db.execute(
            stmt.order_by(Agent.created_at.desc())
            .offset((page - 1) * page_size).limit(page_size)
        ).scalars())

        shadow_by_agent = self._shadow_conditions(actor, [a.id for a in rows])

        items = []
        for agent in rows:
            mode = effective_mode(agent)
            if enforcement_mode and mode != enforcement_mode:
                continue
            reach = REACH[mode]
            shadow = shadow_by_agent.get(agent.id)
            if shadow_only and not shadow:
                continue
            items.append({
                "id": str(agent.id),
                "name": agent.name,
                "control_state": agent.control_state,
                "origin_category": agent.origin_category,
                "origin_provider": agent.origin_provider,
                "criticality": agent.criticality,
                "owner_id": str(agent.owner_id) if agent.owner_id else None,
                "lifecycle_status": agent.lifecycle_status,
                "last_observed_at": (agent.last_observed_at.isoformat()
                                     if agent.last_observed_at else None),
                # --- the truthful-affordance signal, straight from 5.7 ---
                "enforcement_mode": mode,
                "enforcement_display": reach.display,
                "enforcement_limits": reach.limits,
                "reaches_boundary_calls": reach.reaches_boundary_calls,
                "reaches_agent_execution": reach.reaches_agent_execution,
                # --- shadow: the conditions, never a bare flag ---
                "shadow": shadow is not None,
                "shadow_conditions": shadow or [],
                "shadow_visible": shadow_by_agent is not _DENIED,
            })
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items,
        }

    def _shadow_conditions(self, actor: User, agent_ids: list[uuid.UUID]) -> dict:
        """Shadow conditions for one page, in one query rather than one per row.

        A caller without ``posture.view`` gets ``_DENIED`` - distinguishable
        from "no shadow findings", so the UI can say "you cannot see posture"
        instead of quietly showing every agent as clean.
        """
        if not agent_ids or not self._may(actor, "posture.view"):
            return _DENIED if agent_ids else {}
        from app.models.posture import PostureFinding
        from app.posture.rules import SHADOW_RULE_IDS

        findings = self.db.execute(
            select(PostureFinding).where(
                PostureFinding.organization_id == actor.organization_id,
                PostureFinding.subject_id.in_(agent_ids),
                PostureFinding.rule_id.in_(tuple(SHADOW_RULE_IDS)),
                PostureFinding.status == "OPEN",
            )
        ).scalars()
        out: dict[uuid.UUID, list[dict]] = {}
        for f in findings:
            out.setdefault(f.subject_id, []).append({
                "rule_id": f.rule_id,
                "severity": f.severity,
                "reason": f.reason,
                "finding_id": str(f.id),
            })
        return out


@dataclass(frozen=True)
class _ModeStub:
    """The two fields ``effective_mode`` reads, for a GROUP BY row that is not
    an ``Agent``. A stub rather than loading every agent, so the estate's mode
    breakdown stays one query."""

    control_state: str
    external_enforcement_mode: str | None


class _DeniedMap(dict):
    """A distinguishable empty: 'you may not see posture', not 'no findings'."""


_DENIED = _DeniedMap()


__all__ = ["CommandCenterService", "Section", "RECENT_WINDOW_HOURS", "DORMANT_DAYS"]
