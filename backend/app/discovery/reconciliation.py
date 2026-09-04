"""Phase 5.2 (M5.2) - ``ReconciliationService``: derives canonical `agents`
state from append-only observations.

**Matching is deterministic and explainable, never opaque ML** (SRS M5.2
§I, §7.4): the sole identity signal is an exact match on
``(organization_id, external_reference)`` -- the column Phase 5.1 already
gave every agent. There is no fuzzy/name-similarity matching in this phase;
it is a documented future extension (see
``docs/discovery/reconciliation.md``), not built here.

**No silent merge, no silent split.** Every observation resolves to exactly
one of three deterministic outcomes:

  * **CREATE** - no agent claims this external identifier yet, and the
    observation's confidence clears the link/create threshold -> a new
    agent is created at ``control_state=DISCOVERED`` through the Phase 5.1
    ``AgentProvenanceService`` seam (never a raw insert).
  * **LINK** - an existing EXTERNAL/UNKNOWN agent already claims this
    identifier and confidence clears the threshold -> its discovery
    metadata (``last_observed_at``, ``discovery_confidence``,
    ``discovery_source_ref``) is updated. **Authoritative fields
    (ownership, control_state, lifecycle_status) are never touched here.**
  * **FLAG** - anything else (confidence below threshold, or the identifier
    already belongs to a NATIVE, ACT-governed agent -- a genuine conflict,
    never silently resolved either way) -> a ``discovery_findings`` row for
    a human to resolve. No automatic link, no automatic split.

Staleness (``check_staleness``) is the same non-destructive discipline:
an agent linked to a source but missing from enough consecutive sweeps
(``DiscoverySource.missed_sweeps_before_stale``) gets an OPEN
``STALE_AGENT`` finding -- never a deletion, never a ``control_state``
change. Reappearing resolves the finding automatically.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.identity.errors import IdentityError
from app.models.agent import Agent
from app.models.discovery import DiscoveryFinding, DiscoveryObservation, DiscoveryRun, DiscoverySource
from app.models.user import User
from app.runtime.registry.control import AgentProvenanceService
from app.runtime.services import _now, _record_event

#: Below this, an observation never auto-creates or auto-links -- it is
#: always a finding. Deterministic and documented, not tunable per-call.
LINK_CREATE_CONFIDENCE_THRESHOLD = Decimal("0.75")

# Malicious/oversized external metadata is bounded here, not trusted from
# any adapter (SRS M5.2 §10 threat model) -- these mirror the canonical
# `agents` columns an observation ultimately feeds (`name` VARCHAR(255),
# `origin_provider` VARCHAR(50)). `external_identifier` is bounded earlier,
# at observation-persist time (see `DiscoveryRunService._persist_observations`),
# to the same length as `Agent.external_reference` -- the one choke point
# every external identifier passes through, so matching, creation and
# staleness's re-observation check always agree on the same value. A `Text`
# field (`description`) still gets a generous, finite cap so no single
# hostile item can produce an unbounded write.
_MAX_NAME = 255
_MAX_ORIGIN_PROVIDER = 50
_MAX_DESCRIPTION = 4000


def _bounded(value: str | None, max_len: int) -> str | None:
    if value is None:
        return None
    return value[:max_len]


class ReconciliationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Observation -> canonical state
    # ------------------------------------------------------------------ #
    def reconcile(self, actor: User, run: DiscoveryRun, source: DiscoverySource,
                 observations: list[DiscoveryObservation]) -> dict:
        created = linked = flagged = 0
        for obs in observations:
            outcome = self._reconcile_one(actor, run, source, obs)
            if outcome == "CREATED":
                created += 1
            elif outcome == "LINKED":
                linked += 1
            else:
                flagged += 1
        return {"created": created, "linked": linked, "flagged": flagged}

    def _existing_agent(self, source: DiscoverySource, external_identifier: str) -> Agent | None:
        return self.db.execute(
            select(Agent).where(Agent.organization_id == source.organization_id,
                                Agent.external_reference == external_identifier)
        ).scalars().first()

    def _reconcile_one(self, actor: User, run: DiscoveryRun, source: DiscoverySource,
                       obs: DiscoveryObservation) -> str:
        # `obs.external_identifier` is already bounded to `Agent.external_reference`'s
        # own length at observation-persist time (`DiscoveryRunService._persist_observations`)
        # -- the single choke point every external identifier passes through, so
        # matching/creation and staleness's own re-observation check always agree.
        external_ref = obs.external_identifier
        existing = self._existing_agent(source, external_ref)

        if existing is not None and existing.origin_category == "NATIVE":
            self._raise_finding(
                actor, source, run_id=run.id, observation_id=obs.id,
                external_identifier=external_ref, confidence=obs.confidence,
                agent_id=existing.id,
                reason=(f"external_identifier {external_ref!r} matches native, "
                        f"ACT-governed agent {existing.id} - a conflict, not a discovery target. "
                        "No automatic action taken."),
            )
            return "FLAGGED"

        if obs.confidence < LINK_CREATE_CONFIDENCE_THRESHOLD:
            self._raise_finding(
                actor, source, run_id=run.id, observation_id=obs.id,
                external_identifier=external_ref, confidence=obs.confidence,
                agent_id=existing.id if existing else None,
                reason=(f"observation confidence {obs.confidence} is below the "
                        f"{LINK_CREATE_CONFIDENCE_THRESHOLD} link/create threshold."),
            )
            return "FLAGGED"

        payload = obs.normalized_payload or {}
        if existing is None:
            try:
                new_agent = AgentProvenanceService(self.db).record_external_agent(
                    actor, name=_bounded(str(payload.get("name") or external_ref), _MAX_NAME),
                    origin_category="EXTERNAL",
                    origin_provider=_bounded(str(payload.get("origin_provider") or "UNKNOWN"),
                                             _MAX_ORIGIN_PROVIDER),
                    external_reference=external_ref,
                    description=_bounded(payload.get("description"), _MAX_DESCRIPTION),
                    discovery_source_ref=str(source.id), first_observed_at=obs.observed_at,
                    last_observed_at=obs.observed_at, match_confidence=obs.confidence,
                )
            except (IntegrityError, IdentityError):
                # Lost a concurrent create race for this exact
                # external_identifier (M5.2-AC-10) - never a duplicate
                # agent: fall back to LINK against the winner's row.
                self.db.rollback()
                existing = self._existing_agent(source, external_ref)
                if existing is None:  # pragma: no cover - defensive; the race implies a winner exists
                    self._raise_finding(
                        actor, source, run_id=run.id, observation_id=obs.id,
                        external_identifier=external_ref, confidence=obs.confidence,
                        agent_id=None, reason="Create failed and no concurrent winner was found.",
                    )
                    return "FLAGGED"
            else:
                _record_event(self.db, AuthorizationAuditEvent.DISCOVERY_AGENT_CREATED, actor,
                             organization_id=source.organization_id, agent_id=new_agent.id,
                             meta={"source_id": str(source.id), "external_identifier": external_ref,
                                   "confidence": str(obs.confidence)})
                self.db.commit()
                return "CREATED"

        # LINK - discovery metadata only. Never touches ownership,
        # control_state or lifecycle_status.
        existing.last_observed_at = obs.observed_at
        if existing.first_observed_at is None:
            existing.first_observed_at = obs.observed_at
        existing.discovery_confidence = obs.confidence
        existing.discovery_source_ref = str(source.id)
        existing.updated_by = actor.id
        _record_event(self.db, AuthorizationAuditEvent.DISCOVERY_AGENT_LINKED, actor,
                     organization_id=source.organization_id, agent_id=existing.id,
                     meta={"source_id": str(source.id), "external_identifier": external_ref,
                           "confidence": str(obs.confidence)})
        self.db.commit()
        return "LINKED"

    def _raise_finding(self, actor: User, source: DiscoverySource, *, run_id: uuid.UUID | None,
                       observation_id: uuid.UUID | None, external_identifier: str | None,
                       confidence: Decimal | None, agent_id: uuid.UUID | None, reason: str) -> None:
        finding = DiscoveryFinding(
            organization_id=source.organization_id, finding_type="RECONCILIATION_AMBIGUOUS",
            source_id=source.id, run_id=run_id, observation_id=observation_id, agent_id=agent_id,
            external_identifier=external_identifier, confidence=confidence, reason=reason, status="OPEN",
        )
        self.db.add(finding)
        _record_event(self.db, AuthorizationAuditEvent.DISCOVERY_FINDING_RAISED, actor,
                     organization_id=source.organization_id, agent_id=agent_id,
                     meta={"source_id": str(source.id), "finding_type": "RECONCILIATION_AMBIGUOUS",
                           "external_identifier": external_identifier})
        self.db.commit()

    # ------------------------------------------------------------------ #
    # Staleness - non-destructive, reversible, deterministic
    # ------------------------------------------------------------------ #
    def check_staleness(self, actor: User, source: DiscoverySource, *,
                        observed_external_ids: set[str]) -> dict:
        linked_agents = list(self.db.execute(
            select(Agent).where(Agent.organization_id == source.organization_id,
                                Agent.discovery_source_ref == str(source.id),
                                Agent.origin_category.in_(("EXTERNAL", "UNKNOWN")))
        ).scalars())

        raised = resolved = 0
        for agent in linked_agents:
            open_finding = self.db.execute(
                select(DiscoveryFinding).where(DiscoveryFinding.agent_id == agent.id,
                                               DiscoveryFinding.finding_type == "STALE_AGENT",
                                               DiscoveryFinding.status == "OPEN")
            ).scalars().first()

            if agent.external_reference in observed_external_ids:
                if open_finding is not None:
                    open_finding.status = "RESOLVED"
                    open_finding.resolved_at = _now()
                    _record_event(self.db, AuthorizationAuditEvent.DISCOVERY_FINDING_RESOLVED, actor,
                                 organization_id=source.organization_id, agent_id=agent.id,
                                 meta={"source_id": str(source.id), "finding_type": "STALE_AGENT",
                                       "reason": "re-observed"})
                    self.db.commit()
                    resolved += 1
                continue

            if open_finding is not None:
                continue  # already flagged; deterministic idempotency, not a new finding per miss

            # Deterministic miss count: completed sweeps of this source since
            # this agent was last observed. missed_sweeps_before_stale=1
            # (the default) means the very next miss raises.
            since = agent.last_observed_at
            prior_misses = 0
            if since is not None:
                prior_misses = self.db.execute(
                    select(func.count(DiscoveryRun.id)).where(
                        DiscoveryRun.source_id == source.id,
                        DiscoveryRun.status.in_(("SUCCEEDED", "PARTIAL")),
                        DiscoveryRun.started_at > since,
                    )
                ).scalar() or 0
            if prior_misses + 1 < source.missed_sweeps_before_stale:
                continue

            finding = DiscoveryFinding(
                organization_id=source.organization_id, finding_type="STALE_AGENT",
                source_id=source.id, agent_id=agent.id, reason=(
                    f"Agent {agent.id} (external_identifier={agent.external_reference!r}) was not "
                    f"observed in the latest sweep of source {source.name!r}; last observed "
                    f"{agent.last_observed_at.isoformat() if agent.last_observed_at else 'never'}. "
                    "This is a finding, not a deletion - control_state is unchanged."
                ), status="OPEN",
            )
            self.db.add(finding)
            try:
                self.db.commit()
            except IntegrityError:
                # The partial unique index (one OPEN staleness finding per
                # agent) caught a concurrent raiser - correct outcome, not
                # an error.
                self.db.rollback()
                continue
            _record_event(self.db, AuthorizationAuditEvent.DISCOVERY_FINDING_RAISED, actor,
                         organization_id=source.organization_id, agent_id=agent.id,
                         meta={"source_id": str(source.id), "finding_type": "STALE_AGENT"})
            self.db.commit()
            raised += 1

        return {"raised": raised, "resolved": resolved}


__all__ = ["ReconciliationService", "LINK_CREATE_CONFIDENCE_THRESHOLD"]
