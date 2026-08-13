"""ACT-SRS-M3 §Phase-3.4 (M3-3.4-FR-010..014, FR-020..022) -- the hot-path
version resolver and, in the same mechanism, ruling #4's execution gate.

**What this is.** Given (agent, environment) it finds the servable
deployment(s), reads the current traffic allocation, and selects one
immutable version to run. "Resolve a version from an active deployment's
allocation, else fail closed" *is* both the routing logic and the gate --
which is why they are one object and not two.

**Where it sits, and what it must not do.** It is called from exactly one
place, ``ExecutionRequestService._request_execution``
(``app.runtime.services``), between the agent-lifecycle checks and the
creation of the ``AgentExecution`` row -- i.e. strictly *before* the existing
``authorize(deployment)`` call, which is left completely untouched.

    agent checks -> [THIS RESOLVER] -> execution row -> AuthorizationGateway
                                                        -> runtime policy
                                                        -> queue -> worker

The resolver **selects a version; it never dispatches one**. Every
authorization decision still happens afterwards, in the pre-existing
``AuthorizationGateway`` call, on the resolved version's execution, exactly
as before this phase. A resolver that resolved-and-dispatched would be an
authorization bypass -- the sharpest line in this milestone (§27 §10.2) --
so this module imports no gateway, no policy engine, and no worker, and
returns a plain value rather than acting on one. It also never assigns to an
``AgentVersion`` (§3.2 immutability); it only reads.

**No new locks.** The resolver issues at most three indexed SELECTs and takes
no lock of its own, so it cannot deadlock against the locks the execution
path already holds (§9, the Milestone 1 deadlock lesson).

**Implicit vs. explicit allocation.** An agent with a servable deployment but
no allocation row for its environment resolves to that deployment's own
version -- an *implicit 100% allocation*. This is what keeps every agent that
could execute before this phase executing after it (AC-11): migration 0040
materialises explicit 100% rows for deployments that existed at upgrade time,
and this rule covers deployments created afterwards without anyone having to
set weights first. The gate is not weakened by it: a servable deployment is
still required, and that requirement is what ruling #4 asks for.

**Caching: deliberately none.** Correctness first (FR-030 makes caching
optional and demands proven invalidation). The lookup is already three
indexed queries against small per-agent working sets, and every candidate
cache key here -- deployment state, allocation revision, version status --
is mutated by code paths spread across three phases (pause, supersede,
rollback, revoke, kill switch), so a cache would need an invalidation hook in
all of them to stay correct under the kill switch. That is a fail-closed
hazard bought for an unmeasured gain, so this phase measures first and caches
never. See docs/deployment/traffic-and-resolution.md for the benchmark."""

from __future__ import annotations

import hashlib
import random
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.runtime import (
    AgentDeployment,
    AgentVersion,
    DeploymentTrafficWeight,
)
from app.runtime.deployment.traffic import (
    SERVABLE_VERSION_STATUSES,
    TrafficAllocationService,
    is_servable,
    servable_clause,
)


@dataclass(frozen=True, slots=True)
class ResolvedVersion:
    """What the resolver hands back to the execution path: which immutable
    version to run and which deployment serves it, plus the routing metadata
    worth auditing. A plain value -- the caller does the authorizing."""

    deployment: AgentDeployment
    version: AgentVersion
    allocation_id: uuid.UUID | None
    allocation_revision: int | None
    weight: int | None
    routing_key: str | None

    @property
    def routed_by_allocation(self) -> bool:
        return self.allocation_id is not None


def select_weighted(entries: list[DeploymentTrafficWeight], routing_key: str | None) -> DeploymentTrafficWeight:
    """Pick one entry with probability proportional to its weight.

    With a ``routing_key`` the choice is a pure function of that key and the
    entry set, so the same key always lands on the same version (FR-012's
    sticky routing) with no stored session state. Entries are ordered by
    version id first, so the cumulative walk does not depend on the order
    rows happened to come back in.

    Changing the weights deliberately re-shuffles which keys map where -- a
    key is sticky *for a given allocation*, which is what makes a canary
    meaningful; it is not a permanent pin."""
    ordered = sorted(entries, key=lambda e: str(e.agent_version_id))
    total = sum(entry.weight for entry in ordered)
    if routing_key is not None:
        digest = hashlib.sha256(routing_key.encode("utf-8")).hexdigest()
        bucket = int(digest[:16], 16) % total
    else:
        bucket = random.randrange(total)
    cumulative = 0
    for entry in ordered:
        cumulative += entry.weight
        if bucket < cumulative:
            return entry
    return ordered[-1]  # unreachable: bucket < total == cumulative


class VersionResolver:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _servable_deployments(self, agent: Agent, environment: str | None) -> list[AgentDeployment]:
        """Query 1 of at most 3. Indexed on ``agent_deployments(agent_id)``
        plus the two state columns' own indexes; ordered so the choice of
        primary deployment is deterministic and matches the pre-existing
        ``DeploymentService.active_for_agent`` ordering (newest first)."""
        stmt = (select(AgentDeployment)
               .where(AgentDeployment.organization_id == agent.organization_id,
                      AgentDeployment.agent_id == agent.id,
                      servable_clause())
               .order_by(AgentDeployment.deployed_at.desc().nullslast(), AgentDeployment.id))
        if environment:
            stmt = stmt.where(AgentDeployment.environment == environment)
        return list(self.db.execute(stmt).scalars())

    def resolve(self, agent: Agent, *, deployment_id: uuid.UUID | None = None,
               environment: str | None = None, routing_key: str | None = None) -> ResolvedVersion:
        """(agent, environment) -> active deployment -> allocation -> version.

        Raises, fail-closed, when nothing is servable:

        - ``DEPLOYMENT_NOT_FOUND`` -- no deployment at all (the pre-existing
          Milestone 1 code and status, unchanged).
        - ``DEPLOYMENT_NOT_ACTIVE`` -- the deployment the caller pinned is not
          servable (likewise unchanged).
        - ``NO_ACTIVE_DEPLOYMENT`` -- this phase's genuinely new mode: an
          allocation exists but every version it weights has become
          unservable (paused, superseded, revoked). Never silently falls back
          to an arbitrary version.
        """
        # A caller naming a deployment explicitly is pinning it (the
        # pre-existing ``deployment_id`` request field). Honour the pin
        # rather than re-routing it through weights -- an operator testing
        # one specific deployment must get that deployment. Tenant and
        # servability are still enforced, with the exact Milestone 1 codes.
        if deployment_id is not None:
            deployment = self.db.get(AgentDeployment, deployment_id)
            if deployment is None or deployment.organization_id != agent.organization_id:
                raise IdentityError(ErrorCode.DEPLOYMENT_NOT_FOUND,
                                   "No active deployment for this agent.")
            if not is_servable(deployment):
                raise IdentityError(ErrorCode.DEPLOYMENT_NOT_ACTIVE, "Deployment is not active.")
            version = self.db.get(AgentVersion, deployment.agent_version_id)
            return ResolvedVersion(deployment=deployment, version=version, allocation_id=None,
                                   allocation_revision=None, weight=None, routing_key=routing_key)

        candidates = self._servable_deployments(agent, environment)
        if not candidates:
            raise IdentityError(ErrorCode.DEPLOYMENT_NOT_FOUND,
                               "No active deployment for this agent.")
        primary = candidates[0]

        # A deployment with no governed environment row (the legacy
        # string-only create path, still possible per 3.2) cannot carry an
        # allocation, so it resolves implicitly to its own version.
        if primary.environment_id is None:
            return self._implicit(primary, routing_key)

        allocation = TrafficAllocationService(self.db).current(  # query 2
            agent.organization_id, agent.id, primary.environment_id)
        if allocation is None:
            return self._implicit(primary, routing_key)

        # Query 3: the weights and, in the same statement, the deployment and
        # version rows needed to re-check servability. One join over a set
        # bounded by the number of versions sharing an environment (a
        # handful), not a per-execution join explosion (FR-014).
        rows = list(self.db.execute(
            select(DeploymentTrafficWeight, AgentDeployment, AgentVersion)
            .join(AgentDeployment, AgentDeployment.id == DeploymentTrafficWeight.deployment_id)
            .join(AgentVersion, AgentVersion.id == DeploymentTrafficWeight.agent_version_id)
            .where(DeploymentTrafficWeight.allocation_id == allocation.id,
                   DeploymentTrafficWeight.weight > 0,
                   AgentVersion.status.in_(tuple(SERVABLE_VERSION_STATUSES)),
                   servable_clause())
        ))
        if not rows:
            # Fail closed (FR-021): an allocation exists but nothing it
            # points at can serve right now. Never fall through to the
            # primary deployment's own version -- that would silently run a
            # version the operator's weights did not choose.
            raise IdentityError(
                ErrorCode.NO_ACTIVE_DEPLOYMENT,
                "No servable version for this agent in this environment: the traffic "
                "allocation's versions are all paused, superseded or revoked.",
            )

        chosen = select_weighted([row[0] for row in rows], routing_key)
        by_weight_id = {row[0].id: row for row in rows}
        _weight, deployment, version = by_weight_id[chosen.id]
        return ResolvedVersion(
            deployment=deployment, version=version, allocation_id=allocation.id,
            allocation_revision=allocation.revision, weight=chosen.weight,
            routing_key=routing_key,
        )

    def _implicit(self, deployment: AgentDeployment, routing_key: str | None) -> ResolvedVersion:
        """The implicit 100% allocation -- see this module's docstring. The
        version's own status is deliberately *not* filtered here: the
        pre-existing Milestone 1 checks in ``_request_execution`` still run
        on it and still raise ``AGENT_VERSION_REVOKED`` /
        ``AGENT_VERSION_NOT_PUBLISHED`` exactly as they always have."""
        version = self.db.get(AgentVersion, deployment.agent_version_id)
        return ResolvedVersion(deployment=deployment, version=version, allocation_id=None,
                               allocation_revision=None, weight=None, routing_key=routing_key)
