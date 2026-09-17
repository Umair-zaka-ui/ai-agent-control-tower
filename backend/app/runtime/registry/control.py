"""Phase 5.1 (M5.1) - Universal Agent Asset Model: provenance, the
control-state dimension, and the minimum safe claim workflow.

``control_state`` answers *"what relationship and real enforcement authority
does ACT currently have over this agent?"* and is deliberately **distinct**
from ``Agent.lifecycle_status`` (the operational 13-state machine in
``registry/services.py``, which this module never reads or writes). A native
agent is ``GOVERNED`` and may be in any lifecycle state; a discovered
external agent is ``DISCOVERED`` and its lifecycle carries no assumption that
ACT executes it.

Every transition here is **server-authoritative**: there is no code path by
which a client submits ``control_state`` and obtains it. The write schemas
(``AgentRegistrationCreate`` / ``AgentRegistryUpdate``) do not carry the
field at all, and the two mutations below authorize through the existing
``AuthorizationGateway`` (at the route), lock the row ``FOR UPDATE``,
re-validate the transition, write the existing ``AgentOwnershipHistory``
ledger and the existing audit trail, and are tenant-scoped by the caller's
``get_or_404``.

Discovery (populating ``first_observed_at`` / ``discovery_source_ref`` / …)
is Phase 5.2. ``AgentProvenanceService.record_external_agent`` is the seam
5.2's reconciliation will call; M5.1 discovers, observes and reconciles
nothing.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.agent_registry import AgentOwnershipHistory
from app.models.user import User
from app.runtime.services import _generate_slug, _now, _record_event, _unique_slug

__all__ = [
    "CONTROL_STATES",
    "ORIGIN_CATEGORIES",
    "ORIGIN_PROVIDERS",
    "CONTROL_TRANSITIONS",
    "LEGAL_CONTROL_STATES_BY_ORIGIN",
    "is_origin_compatible",
    "AgentProvenanceService",
    "AgentControlStateService",
]

# The control-state dimension (SRS M5.1 §8). Orthogonal to lifecycle_status.
CONTROL_STATES: tuple[str, ...] = ("DISCOVERED", "CLAIMED", "REGISTERED", "GOVERNED")

# Provenance category (SRS M5.1 §9) - small + stable, carries a CHECK.
ORIGIN_CATEGORIES: tuple[str, ...] = ("NATIVE", "EXTERNAL", "UNKNOWN")

# Soft provider vocabulary - informational only. NOT enforced in the DB and
# NOT exhaustive: a new vendor is simply a new string, never a schema change.
ORIGIN_PROVIDERS: tuple[str, ...] = (
    "ACT_NATIVE",
    "MICROSOFT",
    "AWS",
    "GOOGLE",
    "OPENAI",
    "ANTHROPIC",
    "LANGGRAPH",
    "CREWAI",
    "CUSTOM",
    "UNKNOWN",
)

# The origin x control-state invariant (V0.2 / ADR-0023): which control
# states are *truthful* for an agent of a given provenance.
#
#   GOVERNED  <=>  NATIVE
#
# ``GOVERNED`` is not a label an operator assigns; it is the consequence of a
# fact - ACT executes the agent, therefore holds full 4.3 / kill-switch
# authority over it - and it is the one column Phase 5.6's containment gate and
# Phase 5.7's ``effective_mode()`` read to decide whether enforcement is real.
# A non-native agent at GOVERNED would be the same over-claim 5.7 made
# unstorable for ``external_enforcement_mode`` (``NATIVE_ENFORCED``), in the
# column that matters more. Conversely a native agent is GOVERNED in *every*
# lifecycle_status (DRAFT, ACTIVE, SUSPENDED, RETIRED ...): lifecycle is an
# orthogonal axis, and demoting a native agent would make 5.6 refuse to stop an
# agent ACT is actually running - an under-claim, but a lie all the same.
LEGAL_CONTROL_STATES_BY_ORIGIN: dict[str, frozenset[str]] = {
    "NATIVE": frozenset({"GOVERNED"}),
    "EXTERNAL": frozenset({"DISCOVERED", "CLAIMED", "REGISTERED"}),
    "UNKNOWN": frozenset({"DISCOVERED", "CLAIMED", "REGISTERED"}),
}


def is_origin_compatible(origin_category: str, control_state: str) -> bool:
    """The single yes/no the invariant reduces to. Used by the service, and
    by the M5.1 full-population guard's SQL predicate (kept in step by
    ``test_ac09``)."""
    return control_state in LEGAL_CONTROL_STATES_BY_ORIGIN.get(origin_category, frozenset())


# Server-authoritative transition matrix for the *generic* transition
# endpoint. DISCOVERED is left ONLY via ``claim()`` (which needs owner
# context the generic endpoint does not carry), so DISCOVERED has no generic
# successors here. GOVERNED has no edges in either direction: under the
# invariant above only NATIVE agents are GOVERNED, a NATIVE agent never
# leaves it, and no other agent can reach it - the "safe reverses"
# M5.1 anticipated (GOVERNED -> REGISTERED) and the external "enrolment"
# (REGISTERED -> GOVERNED) were both removed by V0.2 / ADR-0023.
CONTROL_TRANSITIONS: dict[str, frozenset[str]] = {
    "DISCOVERED": frozenset(),
    "CLAIMED": frozenset({"REGISTERED"}),
    "REGISTERED": frozenset({"CLAIMED"}),
    "GOVERNED": frozenset(),
}


class AgentProvenanceService:
    """Creates + reads the provenance/discovery dimension of an agent.

    ``record_external_agent`` is the only writer of a non-native origin. It is
    intentionally NOT wired to an HTTP route in M5.1 - Phase 5.2's discovery
    and reconciliation is what will call it. Exposing a speculative
    "create external agent" API now is out of scope (SRS M5.1 §16).
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def record_external_agent(
        self,
        actor: User,
        *,
        name: str,
        origin_category: str = "UNKNOWN",
        origin_provider: str = "UNKNOWN",
        external_reference: str | None = None,
        description: str | None = None,
        discovery_source_ref: str | None = None,
        first_observed_at: datetime | None = None,
        last_observed_at: datetime | None = None,
        match_confidence: Decimal | float | None = None,
    ) -> Agent:
        """Record that an agent existing *outside* ACT has been observed.

        The row lands at ``control_state='DISCOVERED'`` - ACT knows it exists
        and has **no** authority over it. ``lifecycle_status`` is ``DRAFT``:
        the agent has not been through ACT's native validate/approve/activate
        pipeline and this record makes no claim that it ever will be, or that
        ACT executes it.
        """
        if origin_category not in ("EXTERNAL", "UNKNOWN"):
            raise IdentityError(
                ErrorCode.VALIDATION_ERROR,
                "record_external_agent only records EXTERNAL or UNKNOWN origin agents.",
            )
        if external_reference:
            conflict = self.db.execute(
                select(Agent.id).where(
                    Agent.organization_id == actor.organization_id,
                    Agent.external_reference == external_reference,
                )
            ).first()
            if conflict:
                raise IdentityError(
                    ErrorCode.AGENT_EXTERNAL_REFERENCE_CONFLICT,
                    "external_reference is already registered in this organization.",
                )

        slug = _unique_slug(self.db, actor.organization_id, _generate_slug(name))
        agent = Agent(
            organization_id=actor.organization_id,
            name=name,
            description=description,
            agent_type="EXTERNAL",
            api_key_hash="",
            lifecycle_status="DRAFT",
            slug=slug,
            control_state="DISCOVERED",
            origin_category=origin_category,
            origin_provider=origin_provider,
            external_reference=external_reference,
            discovery_source_ref=discovery_source_ref,
            first_observed_at=first_observed_at,
            last_observed_at=last_observed_at,
            discovery_confidence=(
                Decimal(str(match_confidence)) if match_confidence is not None else None
            ),
            created_by=actor.id,
            updated_by=actor.id,
        )
        self.db.add(agent)
        self.db.flush()
        _record_event(
            self.db,
            AuthorizationAuditEvent.RUNTIME_AGENT_REGISTERED,
            actor,
            organization_id=actor.organization_id,
            agent_id=agent.id,
            meta={
                "agent_id": str(agent.id),
                "name": agent.name,
                "origin_category": origin_category,
                "origin_provider": origin_provider,
                "control_state": "DISCOVERED",
                "discovery_source_ref": discovery_source_ref,
            },
        )
        self.db.commit()
        self.db.refresh(agent)
        return agent


class AgentControlStateService:
    """The server-authoritative control-state machine + the claim workflow.

    Both mutations lock the agent row ``FOR UPDATE`` so concurrent
    claims/transitions serialise: the first commits, the rest re-read and hit
    a deterministic conflict rather than a torn state.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def _lock(self, agent_id: uuid.UUID) -> Agent:
        """``SELECT ... FOR UPDATE``, as a clean load.

        Any copy of this row already in the session is evicted first: without
        that, ``version_id_col`` validation on the locking reload raises
        ``StaleDataError`` the instant a concurrent writer has bumped
        ``row_version`` between our first read and the lock — an ORM-level
        error where we want a re-read of the committed state so the caller can
        surface a domain conflict (``AGENT_CLAIM_CONFLICT`` /
        ``CONTROL_STATE_TRANSITION_INVALID``)."""
        stale = self.db.get(Agent, agent_id)
        if stale is not None:
            self.db.expunge(stale)
        return self.db.get(Agent, agent_id, with_for_update=True)

    def _reject(self, actor: User, locked: Agent, target_state: str, code: ErrorCode,
                message: str, *, reason: str | None) -> IdentityError:
        """A refused control-state move is a security-relevant event in its own
        right (V0.2 / ADR-0023). Record it and **commit before raising** - the
        same discipline as 5.6's ``CONTAINMENT_ACTION_REFUSED`` - so the
        rejection survives the request's rollback. Nothing on the agent row
        was changed, so the commit releases the ``FOR UPDATE`` lock cleanly."""
        _record_event(
            self.db,
            AuthorizationAuditEvent.RUNTIME_AGENT_CONTROL_STATE_REJECTED,
            actor,
            organization_id=locked.organization_id,
            agent_id=locked.id,
            severity="WARNING",
            meta={
                "agent_id": str(locked.id),
                "origin_category": locked.origin_category,
                "control_state": locked.control_state,
                "target_state": target_state,
                "code": str(code),
                "reason": reason,
            },
        )
        self.db.commit()
        return IdentityError(code, message)

    def _require_origin_compatible(self, actor: User, locked: Agent, target_state: str,
                                   *, reason: str | None) -> None:
        """The invariant, applied at the writer: the *target* must be a truthful
        control state for this agent's provenance. Evaluated before the
        transition matrix, because "would be an over-claim" is a more
        fundamental refusal than "no such edge"."""
        if is_origin_compatible(locked.origin_category, target_state):
            return
        if target_state == "GOVERNED":
            message = (
                f"A {locked.origin_category} agent cannot be GOVERNED. GOVERNED means ACT runs "
                "and enforces the agent (it is what Phase 5.6 containment and Phase 5.7's "
                "NATIVE_ENFORCED are derived from); it is true of NATIVE agents only and cannot "
                "be granted by request. Use Phase 5.7's enforcement modes for the reach ACT "
                "genuinely has at the boundary."
            )
        else:
            message = (
                f"A NATIVE agent is GOVERNED in every lifecycle state and cannot be moved to "
                f"{target_state}: ACT runs and enforces it, and recording a weaker control "
                "state would make containment refuse an agent ACT can actually stop."
            )
        raise self._reject(actor, locked, target_state,
                           ErrorCode.CONTROL_STATE_ORIGIN_INCOMPATIBLE, message, reason=reason)

    def claim(
        self,
        actor: User,
        agent: Agent,
        *,
        owner_type: str,
        owner_id: uuid.UUID,
        reason: str,
    ) -> Agent:
        """SRS M5.1 §11 - an authorized user takes *responsibility* for a
        discovered/unclaimed agent. Claim advances control_state to
        ``CLAIMED`` (responsibility), **not** ``GOVERNED`` (enforcement) -
        governance enrollment is a separate, later transition.
        """
        locked = self._lock(agent.id)
        if locked.control_state != "DISCOVERED":
            raise IdentityError(
                ErrorCode.AGENT_CLAIM_CONFLICT,
                f"Only a DISCOVERED agent can be claimed; this agent is {locked.control_state}.",
            )
        # Unreachable for a NATIVE agent (it is never DISCOVERED), asserted
        # anyway: the invariant is checked at every writer, not remembered.
        self._require_origin_compatible(actor, locked, "CLAIMED", reason=reason)
        if owner_type == "USER":
            new_owner = self.db.get(User, owner_id)
            if new_owner is None or new_owner.organization_id != locked.organization_id:
                raise IdentityError(
                    ErrorCode.AGENT_OWNER_SCOPE_MISMATCH,
                    "The claiming owner must belong to this organization.",
                )

        previous_type, previous_id = locked.owner_type, locked.owner_id
        locked.control_state = "CLAIMED"
        locked.owner_type = owner_type
        locked.owner_id = owner_id
        locked.updated_by = actor.id
        self.db.add(
            AgentOwnershipHistory(
                agent_id=locked.id,
                owner_role="BUSINESS_OWNER",
                previous_owner_type=previous_type,
                previous_owner_id=previous_id,
                new_owner_type=owner_type,
                new_owner_id=owner_id,
                reason=reason,
                changed_by=actor.id,
                changed_at=_now(),
            )
        )
        _record_event(
            self.db,
            AuthorizationAuditEvent.RUNTIME_AGENT_CLAIMED,
            actor,
            organization_id=locked.organization_id,
            agent_id=locked.id,
            meta={
                "previous_control_state": "DISCOVERED",
                "new_control_state": "CLAIMED",
                "previous_owner_id": str(previous_id) if previous_id else None,
                "new_owner_type": owner_type,
                "new_owner_id": str(owner_id),
                "reason": reason,
            },
        )
        self.db.commit()
        self.db.refresh(locked)
        return locked

    def transition(
        self,
        actor: User,
        agent: Agent,
        target_state: str,
        *,
        reason: str | None = None,
    ) -> Agent:
        """SRS M5.1 §8 - a server-authoritative control-state move
        (CLAIMED <-> REGISTERED). Illegal or unauthorized moves are rejected
        and audited. Since V0.2 / ADR-0023 no move reaches GOVERNED: it is
        true of NATIVE agents only (``LEGAL_CONTROL_STATES_BY_ORIGIN``), and a
        NATIVE agent never leaves it.
        """
        if target_state not in CONTROL_STATES:
            raise IdentityError(
                ErrorCode.CONTROL_STATE_TRANSITION_INVALID,
                f"{target_state!r} is not a control state.",
            )
        locked = self._lock(agent.id)
        # 1. The invariant (V0.2 / ADR-0023): is the target a truthful state
        #    for this agent's provenance at all? Rejected and audited here for
        #    a NATIVE demotion and for any non-native request for GOVERNED.
        self._require_origin_compatible(actor, locked, target_state, reason=reason)
        # 2. The matrix: is there an edge from the current state?
        allowed = CONTROL_TRANSITIONS.get(locked.control_state, frozenset())
        if target_state not in allowed:
            hint = ""
            if locked.control_state == "DISCOVERED":
                hint = " Claim the agent first (POST .../claim)."
            raise self._reject(
                actor, locked, target_state, ErrorCode.CONTROL_STATE_TRANSITION_INVALID,
                f"Cannot move control_state from {locked.control_state} to {target_state}.{hint}",
                reason=reason)
        # 3. Preconditions. Unreachable by construction since V0.2 (no edge
        #    leads to GOVERNED), retained as defence in depth.
        if target_state == "GOVERNED" and locked.owner_id is None:
            raise self._reject(
                actor, locked, target_state, ErrorCode.CONTROL_STATE_TRANSITION_FORBIDDEN,
                "An agent cannot be enrolled into governance without an accountable owner.",
                reason=reason)

        previous = locked.control_state
        locked.control_state = target_state
        locked.updated_by = actor.id
        _record_event(
            self.db,
            AuthorizationAuditEvent.RUNTIME_AGENT_CONTROL_STATE_CHANGED,
            actor,
            organization_id=locked.organization_id,
            agent_id=locked.id,
            meta={
                "previous_control_state": previous,
                "new_control_state": target_state,
                "reason": reason,
            },
        )
        self.db.commit()
        self.db.refresh(locked)
        return locked
