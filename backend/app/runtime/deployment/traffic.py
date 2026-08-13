"""ACT-SRS-M3 §Phase-3.4 (M3-3.4-FR-001..005) -- weighted traffic allocation:
the domain object, its servability predicate, and the one hardened operation
that changes weights.

This module owns two things the rest of the phase builds on.

**1. What "servable" means (the union-with-veto predicate).**

This repository carries *two* deployment state fields, written by disjoint
code (see docs/deployment/lifecycle.md and this package's ``service.py``):

- ``AgentDeployment.status`` -- the Phase 5.0 field. Written by the legacy
  ``DeploymentService.deploy/suspend/resume/rollback/retire`` **and by
  ``KillSwitchService``** (``app.runtime.services``, §60, which sets
  ``status="SUSPENDED"`` and never touches ``lifecycle_state``). This is the
  field the Milestone 1 execution gate has always read.
- ``AgentDeployment.lifecycle_state`` -- the Phase 3.1 fifteen-state machine,
  written *only* by ``DeploymentLifecycleService``. 3.1's ``pause()`` and
  3.2's supersede write only this one.

Neither field alone is a correct gate, and this is not a stylistic choice:

- Gating on ``lifecycle_state`` alone would **disarm the kill switch** at
  ORGANIZATION/PROJECT/PLATFORM scope (it writes only ``status``) -- a
  fail-closed regression the build prompt's §10 forbids outright -- and would
  strand every deployment activated through the legacy route, which leaves
  ``lifecycle_state`` at ``DRAFT``.
- Gating on ``status`` alone would let a 3.1-paused deployment keep serving
  (``pause()`` writes only ``lifecycle_state``), failing AC-10, and would
  leave every 3.2-promoted deployment permanently unable to execute.

So a deployment serves iff **either machine says ACTIVE and neither machine
vetoes**::

    servable(d) = (d.status == "ACTIVE" or d.lifecycle_state == "ACTIVE")
                  and d.status not in NON_SERVING_STATUS
                  and d.lifecycle_state not in NON_SERVING_LIFECYCLE

Both machines keep a veto, so every existing stop signal -- the kill switch,
a legacy suspend, a 3.1 pause, a 3.2 supersede -- still stops traffic, and
neither machine has to be rewritten to drive the other. See
docs/deployment/traffic-and-resolution.md for the full truth table.

**2. Changing weights -- the hardened operation (§27 §4.5).**

An attacker who can redirect traffic to a version of their choosing owns the
agent's behaviour, so ``TrafficAllocationService.set_weights`` is authorized
by its route, tenant-checked, version-eligibility-checked, idempotent
(reusing 3.1's ``IdempotencyService`` verbatim -- never a second mechanism),
audited, and atomic. It never mutates an existing allocation: it writes a new
revision and clears the previous one's ``is_current`` in a single
transaction, so a partial or non-100 state is never committed and therefore
never observable (FR-003).

Concurrency is settled by the partial unique index on
``(agent_id, environment_id) WHERE is_current`` (migration 0040), not by an
advisory lock -- deliberately lock-free, so nothing here can ever deadlock
against the execution path's own locks (§9, the Milestone 1 lesson). Two
racing writers both try to insert a current allocation; Postgres lets exactly
one commit and the loser's ``IntegrityError`` becomes
``TRAFFIC_ALLOCATION_CONFLICT``."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authorization.enums import AuthorizationAuditEvent
from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.runtime import (
    AgentDeployment,
    AgentVersion,
    DeploymentTrafficAllocation,
    DeploymentTrafficWeight,
    Environment,
)
from app.models.user import User
from app.runtime.deployment.idempotency import IdempotencyService
from app.runtime.services import _record_event

# A deployment in one of these states never serves, whatever the *other*
# field says. ``SUSPENDED`` is how ``KillSwitchService`` halts traffic at
# ORGANIZATION/PROJECT/PLATFORM scope, which is why it must veto.
NON_SERVING_STATUS: frozenset[str] = frozenset({
    "SUSPENDED", "RETIRED", "FAILED", "ROLLING_BACK",
})
NON_SERVING_LIFECYCLE: frozenset[str] = frozenset({
    "PAUSED", "SUPERSEDED", "RETIRED", "FAILED", "ROLLING_BACK",
    "REJECTED", "VALIDATION_FAILED",
})

# Version statuses that may be *routed to*. Mirrors the pre-existing
# Milestone 1 execution-path check in ``ExecutionRequestService.
# _request_execution`` exactly (REVOKED is rejected; PUBLISHED and DEPRECATED
# both run) -- this phase narrows nothing about which versions can execute.
SERVABLE_VERSION_STATUSES: frozenset[str] = frozenset({"PUBLISHED", "DEPRECATED"})


def servable_clause() -> ColumnElement[bool]:
    """The union-with-veto predicate as SQL, for the resolver's hot path and
    for eligibility checks. One expression, one definition -- never restated
    at a call site."""
    return and_(
        or_(AgentDeployment.status == "ACTIVE", AgentDeployment.lifecycle_state == "ACTIVE"),
        AgentDeployment.status.notin_(tuple(NON_SERVING_STATUS)),
        AgentDeployment.lifecycle_state.notin_(tuple(NON_SERVING_LIFECYCLE)),
    )


def is_servable(deployment: AgentDeployment) -> bool:
    """The same predicate in Python, for an already-loaded row."""
    return (
        (deployment.status == "ACTIVE" or deployment.lifecycle_state == "ACTIVE")
        and deployment.status not in NON_SERVING_STATUS
        and deployment.lifecycle_state not in NON_SERVING_LIFECYCLE
    )


@dataclass(frozen=True, slots=True)
class WeightEntry:
    """One (version, deployment, weight) triple of a resolved allocation --
    a plain value, never a live ORM row, so the resolver's hot path can hand
    it around without keeping a Session attached."""

    agent_version_id: uuid.UUID
    deployment_id: uuid.UUID
    weight: int


class TrafficAllocationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def current(self, organization_id: uuid.UUID, agent_id: uuid.UUID,
               environment_id: uuid.UUID) -> DeploymentTrafficAllocation | None:
        return self.db.execute(select(DeploymentTrafficAllocation).where(
            DeploymentTrafficAllocation.organization_id == organization_id,
            DeploymentTrafficAllocation.agent_id == agent_id,
            DeploymentTrafficAllocation.environment_id == environment_id,
            DeploymentTrafficAllocation.is_current.is_(True),
        )).scalars().first()

    def weights_for(self, allocation_id: uuid.UUID) -> list[DeploymentTrafficWeight]:
        return list(self.db.execute(
            select(DeploymentTrafficWeight)
            .where(DeploymentTrafficWeight.allocation_id == allocation_id)
            .order_by(DeploymentTrafficWeight.agent_version_id)
        ).scalars())

    def history(self, actor: User, agent_id: uuid.UUID, environment_id: uuid.UUID, *,
               limit: int = 50, offset: int = 0) -> list[DeploymentTrafficAllocation]:
        return list(self.db.execute(
            select(DeploymentTrafficAllocation)
            .where(DeploymentTrafficAllocation.organization_id == actor.organization_id,
                   DeploymentTrafficAllocation.agent_id == agent_id,
                   DeploymentTrafficAllocation.environment_id == environment_id)
            .order_by(DeploymentTrafficAllocation.revision.desc())
            .limit(limit).offset(offset)
        ).scalars())

    # ------------------------------------------------------------------ #
    # Tenant-scoped lookups shared by the routes
    # ------------------------------------------------------------------ #
    def resolve_scope(self, actor: User, agent_id: uuid.UUID,
                     environment_id: uuid.UUID) -> tuple[Agent, Environment]:
        """Both halves of the (agent, environment) key, each tenant-checked.
        Cross-tenant access is a 404 on the object the caller named, never a
        leak that the id exists elsewhere (§7)."""
        agent = self.db.get(Agent, agent_id)
        if agent is None or agent.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.AGENT_NOT_FOUND, "Agent not found.")
        environment = self.db.get(Environment, environment_id)
        if environment is None or environment.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.ENVIRONMENT_NOT_FOUND, "Environment not found.")
        return agent, environment

    # ------------------------------------------------------------------ #
    # Validation (FR-001, FR-002)
    # ------------------------------------------------------------------ #
    def _validate_and_bind(self, agent: Agent, environment: Environment,
                          entries: list[dict]) -> list[WeightEntry]:
        """Rejects an invalid weight set *before* anything is written, and
        binds each version to the active deployment that will serve it.

        Weight-shape problems are ``TRAFFIC_WEIGHTS_INVALID``; a version that
        is simply not allowed to receive weight is ``VERSION_NOT_ELIGIBLE``
        -- two distinct codes because they need two distinct operator
        responses (fix the numbers vs. deploy/publish the version)."""
        if not entries:
            raise IdentityError(ErrorCode.TRAFFIC_WEIGHTS_INVALID,
                               "A traffic allocation must name at least one version.")

        seen: set[uuid.UUID] = set()
        total = 0
        for entry in entries:
            weight = entry["weight"]
            if not isinstance(weight, int) or isinstance(weight, bool):
                raise IdentityError(ErrorCode.TRAFFIC_WEIGHTS_INVALID,
                                   "Every weight must be an integer.")
            if weight < 0 or weight > 100:
                raise IdentityError(ErrorCode.TRAFFIC_WEIGHTS_INVALID,
                                   f"Weight {weight} is outside the range 0-100.")
            version_id = entry["agent_version_id"]
            if version_id in seen:
                raise IdentityError(ErrorCode.TRAFFIC_WEIGHTS_INVALID,
                                   "A version may appear at most once in an allocation.")
            seen.add(version_id)
            total += weight
        if total != 100:
            raise IdentityError(
                ErrorCode.TRAFFIC_WEIGHTS_INVALID,
                f"Traffic weights must total exactly 100; this set totals {total}.",
            )

        bound: list[WeightEntry] = []
        for entry in entries:
            version_id = entry["agent_version_id"]
            version = self.db.get(AgentVersion, version_id)
            if version is None or version.agent_id != agent.id:
                raise IdentityError(
                    ErrorCode.VERSION_NOT_ELIGIBLE,
                    f"Version {version_id} does not belong to this agent.",
                )
            if version.status != "PUBLISHED":
                raise IdentityError(
                    ErrorCode.VERSION_NOT_ELIGIBLE,
                    f"Version {version.version} is {version.status}, not PUBLISHED.",
                )
            # Every version that reaches PUBLISHED is signed -- publish()
            # fails closed if signing fails (see AgentVersionService.publish).
            # Checked anyway: an unsigned version receiving live traffic is
            # exactly the integrity hole this rule exists to close.
            if version.signature_id is None:
                raise IdentityError(
                    ErrorCode.VERSION_NOT_ELIGIBLE,
                    f"Version {version.version} is not signed.",
                )
            deployment = self.db.execute(
                select(AgentDeployment)
                .where(AgentDeployment.organization_id == agent.organization_id,
                       AgentDeployment.agent_id == agent.id,
                       AgentDeployment.agent_version_id == version.id,
                       AgentDeployment.environment_id == environment.id,
                       servable_clause())
                .order_by(AgentDeployment.deployed_at.desc().nullslast(), AgentDeployment.id)
            ).scalars().first()
            if deployment is None:
                raise IdentityError(
                    ErrorCode.VERSION_NOT_ELIGIBLE,
                    f"Version {version.version} has no active deployment in environment "
                    f"{environment.name}; deploy it there before giving it traffic.",
                )
            bound.append(WeightEntry(agent_version_id=version.id, deployment_id=deployment.id,
                                     weight=entry["weight"]))
        return bound

    # ------------------------------------------------------------------ #
    # The hardened write (FR-003, FR-004, FR-005)
    # ------------------------------------------------------------------ #
    def set_weights(self, actor: User, agent: Agent, environment: Environment,
                   entries: list[dict], *, reason: str | None = None,
                   idempotency_key: str | None = None) -> tuple[dict, bool]:
        from app.runtime.schemas import TrafficAllocationRead  # leaf module

        def _do() -> dict:
            bound = self._validate_and_bind(agent, environment, entries)

            previous = self.current(agent.organization_id, agent.id, environment.id)
            previous_weights = (
                {str(w.agent_version_id): w.weight for w in self.weights_for(previous.id)}
                if previous is not None else {}
            )
            next_revision = (previous.revision + 1) if previous is not None else 1

            allocation = DeploymentTrafficAllocation(
                organization_id=agent.organization_id, agent_id=agent.id,
                environment_id=environment.id, revision=next_revision, is_current=True,
                reason=reason, created_by=actor.id,
            )
            try:
                # The whole write sequence is one try block, not just the
                # commit: the losing writer's ``IntegrityError`` is raised by
                # the *first flush* that emits this INSERT (the ``flush()``
                # below, needed for ``allocation.id``), long before the
                # commit. Guarding only the commit would let a raw
                # ``IntegrityError`` escape as a 500. Same shape, and same
                # reason, as ``DeploymentLifecycleService.transition``'s
                # ``StaleDataError`` handling.
                # Order matters, and is made explicit rather than left to
                # SQLAlchemy's unit-of-work heuristics: the previous row must
                # stop being current *before* the new one is inserted, or the
                # partial unique index sees two current rows for this
                # (agent, environment) mid-flush and rejects the caller's own
                # write. Flushed separately for that reason.
                if previous is not None:
                    previous.is_current = False
                    self.db.flush()

                self.db.add(allocation)
                self.db.flush()
                for item in bound:
                    self.db.add(DeploymentTrafficWeight(
                        allocation_id=allocation.id, agent_version_id=item.agent_version_id,
                        deployment_id=item.deployment_id, weight=item.weight,
                    ))

                _record_event(
                    self.db, AuthorizationAuditEvent.DEPLOYMENT_TRAFFIC_CHANGED, actor,
                    organization_id=agent.organization_id, agent_id=agent.id,
                    meta={
                        "environment": environment.name,
                        "environment_id": str(environment.id),
                        "revision": next_revision,
                        "from": previous_weights,
                        "to": {str(item.agent_version_id): item.weight for item in bound},
                    },
                )
                # One commit for the whole set: the previous revision's
                # ``is_current`` clear, the new allocation, and all of its
                # weights land together or not at all (FR-003).
                self.db.commit()
            except IntegrityError:
                # Lost the race for the partial unique index on
                # (agent_id, environment_id) WHERE is_current -- a concurrent
                # writer already committed a new current allocation.
                self.db.rollback()
                raise IdentityError(
                    ErrorCode.TRAFFIC_ALLOCATION_CONFLICT,
                    "This agent's traffic allocation was changed by another request; "
                    "reload and retry.",
                ) from None
            self.db.refresh(allocation)
            return TrafficAllocationRead.model_validate(
                self.read_model(allocation)).model_dump(mode="json")

        return IdempotencyService(self.db).execute(
            organization_id=actor.organization_id, operation="deployment.traffic.set",
            key=idempotency_key,
            payload={"agent_id": str(agent.id), "environment_id": str(environment.id),
                    "entries": [{"agent_version_id": str(e["agent_version_id"]),
                                "weight": e["weight"]} for e in entries]},
            fn=_do,
        )

    # ------------------------------------------------------------------ #
    # Presentation
    # ------------------------------------------------------------------ #
    def read_model(self, allocation: DeploymentTrafficAllocation) -> dict:
        weights = self.weights_for(allocation.id)
        version_numbers = {
            row.id: row.version for row in self.db.execute(
                select(AgentVersion).where(
                    AgentVersion.id.in_([w.agent_version_id for w in weights] or [uuid.uuid4()])
                )
            ).scalars()
        }
        return {
            "id": allocation.id,
            "organization_id": allocation.organization_id,
            "agent_id": allocation.agent_id,
            "environment_id": allocation.environment_id,
            "revision": allocation.revision,
            "is_current": allocation.is_current,
            "reason": allocation.reason,
            "created_at": allocation.created_at,
            "created_by": allocation.created_by,
            "weights": [
                {
                    "agent_version_id": w.agent_version_id,
                    "version": version_numbers.get(w.agent_version_id),
                    "deployment_id": w.deployment_id,
                    "weight": w.weight,
                }
                for w in weights
            ],
        }
