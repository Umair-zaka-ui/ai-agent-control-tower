"""Phase 5.7 (M5.7) - the two modes that enforce **nothing**: OBSERVED and
ADVISORY.

The value of this module is what it does not contain. It imports no
enforcement authority -- not the kill switch, not the tool or capability
lifecycles, not ``api_key_service.revoke_key``, not the connector lifecycle,
not the Phase 5.6 ``ContainmentOrchestrator``, not this phase's own
``CapabilityBoundary`` or ``dispatch``. ``test_ac03_*`` asserts that over the
AST, which is what makes "OBSERVED performs no enforcement" a structural fact
rather than a promise in a docstring. The same technique Phase 5.6 used to
prove ``app/threat`` implements no enforcement of its own.

**OBSERVED -- ingest, fail open.** Events an external agent submits are
evidence. They ride Phase 4.1's ``emit_event``, which is SAVEPOINT-guarded,
scrubs the payload at construction (Phase 4.8) and *never raises*. A dropped
event degrades observability; it blocks nothing, because there is nothing it
could block -- ACT has no enforcement over this agent to withhold. That is
the §9 plane rule exactly: the telemetry plane is derived and
non-authoritative.

**ADVISORY -- evaluate and recommend, enforce nothing.** ACT reads the real
Phase 4.3 policies for the agent and reports what they *would* require. It
returns a recommendation for a human. It writes no policy, revokes no grant,
touches no authority, and the response says so in those words. An operator who
acts on it does so through ACT's ordinary, audited surfaces -- not through
this one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.authorization.services import AuthorizationAuditService
from app.bridge.modes import effective_mode, reach_of
from app.models.agent import Agent
from app.models.user import User

#: Bounds on one ingest request. An OBSERVED agent is, by definition, not
#: under ACT's control -- so the ingest surface is sized for evidence, not
#: trusted to be well-behaved.
MAX_EVENTS_PER_REQUEST = 50
MAX_EVENT_TYPE_LENGTH = 100


@dataclass(frozen=True)
class IngestOutcome:
    """Deliberately reports ``accepted`` *and* ``dropped``. A fail-open path
    that reported only success would be hiding the degradation it is allowed
    to have."""

    accepted: int
    dropped: int
    enforcement_performed: bool = False


@dataclass(frozen=True)
class Recommendation:
    finding: str
    detail: dict[str, Any]
    enforcement_performed: bool = False


class ObservedIngestService:
    """OBSERVED: telemetry in, nothing out. Never gates anything."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def ingest(self, agent: Agent, events: list[dict]) -> IngestOutcome:
        """Record events as evidence. **Never raises** for a bad event.

        Available in every mode, not only OBSERVED: a GATEWAY_ENFORCED or
        NATIVE agent's evidence is just as useful. What never varies is that
        ingesting enforces nothing.
        """
        from app.observability.events import Outcome, emit_event
        from app.observability.attributes import SemanticAttributes

        accepted = dropped = 0
        for raw in (events or [])[:MAX_EVENTS_PER_REQUEST]:
            if not isinstance(raw, dict):
                dropped += 1
                continue
            event_type = str(raw.get("event_type") or "")[:MAX_EVENT_TYPE_LENGTH]
            if not event_type:
                dropped += 1
                continue
            # `emit_event` scrubs the payload at construction and swallows its
            # own failures; `stored` False means the event was dropped, which
            # is reported, not raised.
            stored = emit_event(
                self.db,
                event_type=f"external.{event_type}",
                outcome=Outcome.INFO,
                attributes=SemanticAttributes(
                    organization_id=str(agent.organization_id), agent_id=str(agent.id)),
                payload=raw.get("payload") if isinstance(raw.get("payload"), dict) else None,
                severity="INFO",
            )
            accepted += 1 if stored else 0
            dropped += 0 if stored else 1
        try:
            self.db.commit()
        except Exception:  # noqa: BLE001 -- §9: evidence never gates anything
            self.db.rollback()
            return IngestOutcome(accepted=0, dropped=accepted + dropped)
        return IngestOutcome(accepted=accepted, dropped=dropped)


class AdvisoryService:
    """ADVISORY: evaluate the real policies, recommend, enforce nothing."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def evaluate(self, actor: User, agent: Agent) -> Recommendation:
        from app.runtime.governance.policies import GovernancePolicyService

        policies = GovernancePolicyService(self.db).resolve(
            agent.organization_id, environment_id=None, agent_id=agent.id)
        requiring_approval = [p.name for p in policies
                              if (p.constraints or {}).get("requires_approval") is True]
        mode = effective_mode(agent)
        reach = reach_of(agent)
        detail = {
            "enforcement_mode": mode,
            "policies_considered": len(policies),
            "policies_requiring_approval": requiring_approval,
            "enforcement_reach": reach.display,
            "limits": reach.limits,
            # Stated in the payload, not just the docstring: a consumer that
            # renders this must not be able to mistake it for an action taken.
            "enforcement_performed": False,
        }
        if not policies:
            finding = ("No governance policy applies to this agent. ACT has evaluated and has "
                       "nothing to recommend; it has enforced nothing.")
        elif requiring_approval:
            finding = (f"{len(requiring_approval)} policy/policies would require human approval "
                       "for this agent's governed actions. ACT recommends this to an operator; "
                       "ACT has enforced nothing.")
        else:
            finding = (f"{len(policies)} policy/policies apply and none currently requires "
                       "approval. ACT recommends review; ACT has enforced nothing.")

        AuthorizationAuditService(self.db).record_change(
            AuthorizationAuditEvent.EXTERNAL_ADVISORY_RECOMMENDED,
            organization_id=agent.organization_id, actor_id=actor.id, identity_id=agent.id,
            meta={"enforcement_mode": mode, "policies_considered": len(policies),
                  "policies_requiring_approval": requiring_approval,
                  "enforcement_performed": False},
        )
        self.db.commit()
        return Recommendation(finding=finding, detail=detail)


__all__ = [
    "MAX_EVENTS_PER_REQUEST",
    "MAX_EVENT_TYPE_LENGTH",
    "IngestOutcome",
    "Recommendation",
    "ObservedIngestService",
    "AdvisoryService",
]
