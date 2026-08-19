"""ACT-SRS-M3 §Phase-3.6 (M3-3.6-FR-001..031) -- deployment strategy execution:
one abstraction over ``agent_deployments.deployment_strategy``, with handlers for
RECREATE and BLUE_GREEN.

**What a "strategy" actually is here.** Canary (3.5), RECREATE and BLUE_GREEN are
all *weight transitions over Phase 3.4's traffic allocation*. They differ in the
pattern and in what is preserved, not in the mechanism:

===========  =====================================  ==========================
Strategy     Weight pattern                          What happens to the old
===========  =====================================  ==========================
CANARY (3.5) 5 -> 25 -> 50 -> 100, gated per stage   superseded at the end
RECREATE     0 -> 100 in one cutover                 superseded immediately
BLUE_GREEN   0 (warm) -> 100 in one atomic switch    **preserved at 0%** as a
                                                     rollback target
===========  =====================================  ==========================

So this module builds two new *patterns* and reuses the existing *mechanism*
wholesale: every traffic change goes through
``TrafficAllocationService.set_weights`` (atomic, revisioned, eligibility-checked,
audited), every cutover is gated by Phase 3.3's release gate, every deployment
state change goes through Phase 3.1's lifecycle authority, and the §12 veto is
read from the same fields Phase 3.4's resolver reads. There is no
``DeploymentTrafficWeight`` import in this module, so bypassing 3.4 is
structurally impossible rather than merely discouraged (mechanically checked --
see ``tests/runtime/test_strategies.py``).

**ROLLING is deliberately not implemented (ruling #1, SRS §3.6).** It is declared
in the enum and dispatched to a handler that raises
``STRATEGY_ROLLING_DEFERRED`` -- a real, specific error naming Phase 3.9, never a
fake execution and never a bare ``NotImplemented`` placeholder. The reason is
honest and worth stating: rolling means "replace instances a few at a time", and
this platform has no instance substrate to roll over. The two replica-count
columns on ``agent_deployments`` are vestigial -- the legacy
``DeploymentService.deploy``/``retire`` set them to constants and *nothing reads
them to make any decision*. Implementing rolling against them would produce a
counter that moves while nothing actually rolls: the precise pretence SRS §3.6
forbids. Phase 3.9's worker fleet creates the real substrate, and
``RollingStrategy`` below is the seam it fills.

(Those columns are named indirectly here on purpose: Phase 3.1's own
mechanically-enforced test asserts their names appear *nowhere* in this package,
prose included -- a stricter and better guard than "don't assign to them", and
one this module keeps rather than relaxes.)

**Blue preservation, and why it needs no new table.** After a switch, BLUE stays
lifecycle-ACTIVE but holds **0%** of the allocation. Phase 3.4's resolver skips
zero-weight entries, so BLUE serves nothing -- there is no accidental
split-serving -- while remaining instantly returnable by one more weight change.
The lineage is recorded on the existing ``AgentVersion.rollback_target_id``
through ``VersionLineageService.set_rollback_target`` (its own validator, not a
raw column write), which until now was a settable pointer nothing acted on. It is
also what makes "prepared" inferable without new state: GREEN carries a
zero-weight entry in the current allocation exactly when it has been warmed."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.authorization.enums import AuthorizationAuditEvent
from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.runtime import AgentDeployment, AgentVersion, Environment
from app.models.user import User
from app.runtime.deployment.idempotency import IdempotencyService
from app.runtime.deployment.service import DeploymentLifecycleService
from app.runtime.deployment.traffic import TrafficAllocationService, is_servable, servable_clause
from app.runtime.release_gate.service import ReleaseGateService
from app.runtime.services import _record_event
from app.runtime.versioning.lineage import VersionLineageService

# The four values ``agent_deployments.deployment_strategy`` may hold. Already
# constrained to exactly this set by ``app.runtime.schemas``'s own
# ``_STRATEGY`` pattern since Phase 5.0 -- this phase is the first code to
# actually *dispatch* on the column, which until now was pure data.
STRATEGIES: frozenset[str] = frozenset({"RECREATE", "BLUE_GREEN", "ROLLING", "CANARY"})


@dataclass(frozen=True, slots=True)
class StrategyOutcome:
    """What a strategy operation did, as a plain JSON-safe value -- so it can
    be stored verbatim in 3.1's idempotency ``result_ref`` and replayed."""

    strategy: str
    operation: str
    deployment_id: str
    candidate_version_id: str
    previous_version_id: str | None
    candidate_weight: int
    previous_weight: int
    allocation_revision: int
    detail: str

    def as_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "operation": self.operation,
            "deployment_id": self.deployment_id,
            "candidate_version_id": self.candidate_version_id,
            "previous_version_id": self.previous_version_id,
            "candidate_weight": self.candidate_weight,
            "previous_weight": self.previous_weight,
            "allocation_revision": self.allocation_revision,
            "detail": self.detail,
        }


class DeploymentStrategyHandler(ABC):
    """One strategy's execution. Handlers hold no state; the service passes
    everything in, so dispatch is a dictionary lookup rather than a factory."""

    name: str

    @abstractmethod
    def execute(self, service: "DeploymentStrategyService", actor: User,
               deployment: AgentDeployment) -> StrategyOutcome:
        """Perform this strategy's *primary* operation for ``deployment``.

        For RECREATE that is the cutover. For BLUE_GREEN it is the prepare
        (warm GREEN at 0%) -- the switch is a second, separate decision and so
        a second, separate operation, because an operator warming a candidate
        has not thereby agreed to send it production traffic."""


class RecreateStrategy(DeploymentStrategyHandler):
    """M3-3.6-FR-010..012 -- a single clean cutover, no overlap.

    The candidate goes to 100% and the previously-serving deployment is
    superseded through the 3.1 lifecycle authority, which makes it non-servable
    under 3.4's union-with-veto predicate (``SUPERSEDED`` is in
    ``NON_SERVING_LIFECYCLE``) -- that is what "stops receiving new work" means
    concretely here. Executions already running are untouched; this changes
    what is *routed*, not what is mid-flight.

    Atomicity (FR-012) is inherited, not re-implemented: both weights move in
    one ``set_weights`` call, which 3.4 commits as a single new allocation
    revision. There is no committed state in which neither version serves or
    both serve fully."""

    name = "RECREATE"

    def execute(self, service: "DeploymentStrategyService", actor: User,
               deployment: AgentDeployment) -> StrategyOutcome:
        agent, environment = service.scope_for(deployment)
        service.assert_not_vetoed(agent, deployment)
        service.assert_gate_passes(actor, deployment)

        previous = service.serving_deployment_other_than(deployment)
        previous_version_id = previous.agent_version_id if previous is not None else None

        revision = service.apply_weights(
            actor, agent, environment,
            candidate_version_id=deployment.agent_version_id, candidate_weight=100,
            other_version_id=previous_version_id, other_weight=0,
            reason=f"RECREATE cutover to version {deployment.agent_version_id}.",
        )

        # Supersede *after* traffic has moved: doing it first would make the
        # old deployment non-servable, and 3.4 rejects weight on a version with
        # no servable deployment -- the cutover would fail on its own
        # precondition.
        if previous is not None:
            previous.superseded_by_deployment_id = deployment.id
            DeploymentLifecycleService(service.db).transition(
                actor, previous, "SUPERSEDED",
                reason=f"Superseded by RECREATE cutover to deployment {deployment.id}.")

        service.record(actor, deployment, AuthorizationAuditEvent.DEPLOYMENT_SUCCEEDED,
                      {"strategy": "RECREATE", "operation": "cutover",
                       "superseded_deployment_id": str(previous.id) if previous else None})
        return StrategyOutcome(
            strategy="RECREATE", operation="cutover", deployment_id=str(deployment.id),
            candidate_version_id=str(deployment.agent_version_id),
            previous_version_id=str(previous_version_id) if previous_version_id else None,
            candidate_weight=100, previous_weight=0, allocation_revision=revision,
            detail=("Candidate cut over to 100%; the previous deployment was superseded and "
                   "stops receiving new work."),
        )


class BlueGreenStrategy(DeploymentStrategyHandler):
    """M3-3.6-FR-020..024 -- warm, switch atomically, preserve BLUE.

    ``execute`` is the *prepare* step: BLUE keeps 100% while GREEN is brought to
    a servable, gate-passing state holding 0% of traffic. The switch
    (``DeploymentStrategyService.blue_green_switch``) and the rollback
    (``blue_green_rollback``) are separate operations."""

    name = "BLUE_GREEN"

    def execute(self, service: "DeploymentStrategyService", actor: User,
               deployment: AgentDeployment) -> StrategyOutcome:
        agent, environment = service.scope_for(deployment)
        service.assert_not_vetoed(agent, deployment)
        # Validation is the gate (FR-021). Warming a candidate that could not
        # pass the gate would be pointless work and a misleading "ready" signal.
        service.assert_gate_passes(actor, deployment)

        blue = service.serving_deployment_other_than(deployment)
        if blue is None:
            raise IdentityError(
                ErrorCode.VALIDATION_ERROR,
                "Blue-green needs a currently-serving BLUE deployment to switch away from. "
                "This agent has nothing else serving in this environment, so there is no "
                "blue to preserve -- use RECREATE for a first or uncontested deployment.",
            )

        revision = service.apply_weights(
            actor, agent, environment,
            candidate_version_id=deployment.agent_version_id, candidate_weight=0,
            other_version_id=blue.agent_version_id, other_weight=100,
            reason=f"BLUE_GREEN prepare: GREEN {deployment.agent_version_id} warmed at 0%.",
        )
        service.record(actor, deployment, AuthorizationAuditEvent.DEPLOYMENT_STARTED,
                      {"strategy": "BLUE_GREEN", "operation": "prepare",
                       "blue_version_id": str(blue.agent_version_id)})
        return StrategyOutcome(
            strategy="BLUE_GREEN", operation="prepare", deployment_id=str(deployment.id),
            candidate_version_id=str(deployment.agent_version_id),
            previous_version_id=str(blue.agent_version_id),
            candidate_weight=0, previous_weight=100, allocation_revision=revision,
            detail=("GREEN is deployed, gate-passing and servable, holding 0% of traffic. "
                   "BLUE continues to serve 100%. Call switch when ready."),
        )


class RollingStrategy(DeploymentStrategyHandler):
    """M3-3.6-FR-030/031, implemented in Phase 3.9 over the real worker fleet.

    Phase 3.6 left this class raising ``STRATEGY_ROLLING_DEFERRED`` and said
    filling the seam "requires no change anywhere else in this module". That
    turned out to be true: this is the only edit 3.9 made here.

    Rolling's *primary* operation is beginning the conversion -- deriving the
    fleet's cohorts, creating the plan, and taking the first step. The
    remaining steps are separate decisions and therefore separate calls, the
    same way BLUE_GREEN's switch is not folded into its prepare. The work
    itself lives in ``app.runtime.deployment.rolling``; this handler is the
    dispatch point, and the import is deferred to call time because that
    module imports this one (it reuses ``DeploymentStrategyService``'s veto
    and gate checks rather than restating them)."""

    name = "ROLLING"

    def execute(self, service: "DeploymentStrategyService", actor: User,
               deployment: AgentDeployment) -> StrategyOutcome:
        from app.runtime.deployment.rolling import RollingDeploymentService

        rolling = RollingDeploymentService(service.db)
        result, _replayed = rolling.start(actor, deployment)
        steps = ((result.get("cohort_plan") or {}).get("steps") or [])
        first = steps[0] if steps else {}
        return StrategyOutcome(
            strategy="ROLLING", operation="start", deployment_id=str(deployment.id),
            candidate_version_id=str(deployment.agent_version_id),
            previous_version_id=(str(result["stable_version_id"])
                                 if result.get("stable_version_id") else None),
            candidate_weight=int(first.get("target_weight", 0)),
            previous_weight=100 - int(first.get("target_weight", 0)),
            allocation_revision=int(result.get("allocation_revision") or 0),
            detail=(
                f"Rolling conversion started over {len(steps)} real worker cohort(s) "
                f"({first.get('total_capacity', 0)} slots of live fleet capacity). "
                f"Cohort {first.get('cohort')!r} converted; candidate at "
                f"{first.get('target_weight', 0)}%. Advance the rollout to convert the rest."
            ),
        )


class CanaryStrategyPointer(DeploymentStrategyHandler):
    """CANARY is implemented -- by Phase 3.5's rollout engine, which is a
    multi-step, stateful plan rather than a single operation. Dispatching it
    here would either duplicate that engine or silently do something narrower
    than the caller expects, so this points at the real API instead."""

    name = "CANARY"

    def execute(self, service: "DeploymentStrategyService", actor: User,
               deployment: AgentDeployment) -> StrategyOutcome:
        raise IdentityError(
            ErrorCode.VALIDATION_ERROR,
            "CANARY is executed by the rollout engine, not as a single strategy operation: "
            "POST /api/v1/runtime/agents/{agent_id}/environments/{environment_id}/rollouts "
            "creates a staged canary with per-stage gates.",
        )


_HANDLERS: dict[str, DeploymentStrategyHandler] = {
    handler.name: handler for handler in (
        RecreateStrategy(), BlueGreenStrategy(), RollingStrategy(), CanaryStrategyPointer(),
    )
}


def handler_for(strategy: str) -> DeploymentStrategyHandler:
    """M3-3.6-FR-001 -- the one dispatch point, on the column's value."""
    try:
        return _HANDLERS[strategy]
    except KeyError:
        raise IdentityError(
            ErrorCode.VALIDATION_ERROR,
            f"Unknown deployment strategy {strategy!r}; expected one of {sorted(STRATEGIES)}.",
        ) from None


class DeploymentStrategyService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Lookup + shared preconditions
    # ------------------------------------------------------------------ #
    def get_or_404(self, actor: User, deployment_id: uuid.UUID) -> AgentDeployment:
        deployment = self.db.get(AgentDeployment, deployment_id)
        if deployment is None or deployment.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.DEPLOYMENT_NOT_FOUND, "Deployment not found.")
        return deployment

    def scope_for(self, deployment: AgentDeployment) -> tuple[Agent, Environment]:
        agent = self.db.get(Agent, deployment.agent_id)
        if deployment.environment_id is None:
            raise IdentityError(
                ErrorCode.ENVIRONMENT_NOT_FOUND,
                "This deployment has no governed environment, so its traffic cannot be "
                "allocated. Deployments created through the legacy string-only path in an "
                "organization without seeded environments are not strategy-executable.",
            )
        environment = self.db.get(Environment, deployment.environment_id)
        if environment is None:
            raise IdentityError(ErrorCode.ENVIRONMENT_NOT_FOUND, "Environment not found.")
        return agent, environment

    def assert_not_vetoed(self, agent: Agent, deployment: AgentDeployment) -> None:
        """§12 -- read from the *same* two fields Phase 3.4's resolver reads, so
        a strategy can never activate a version the execution gate would refuse
        to serve. ``KillSwitchService`` suspends the agent at AGENT scope and
        the deployment's ``status`` at ORGANIZATION/PROJECT/PLATFORM scope;
        ``is_servable`` covers the second, this method the first."""
        # Reuses the pre-existing, generic ``KILL_SWITCH_ACTIVE`` (423) rather
        # than 3.5's ``ROLLOUT_HALTED_BY_KILL_SWITCH``: an operator running a
        # blue-green switch has no rollout, and "rollout halted" would be the
        # wrong vocabulary for what they just did. No new code is minted for a
        # condition the platform already names.
        if agent is None or agent.lifecycle_status == "SUSPENDED":
            raise IdentityError(
                ErrorCode.KILL_SWITCH_ACTIVE,
                "This strategy cannot run: the agent is suspended (kill switch or lifecycle "
                "suspension). No strategy activates a suspended agent's version.",
            )
        if agent.lifecycle_status != "ACTIVE":
            raise IdentityError(
                ErrorCode.KILL_SWITCH_ACTIVE,
                f"This strategy cannot run: the agent is {agent.lifecycle_status}, not ACTIVE.",
            )
        if not is_servable(deployment):
            raise IdentityError(
                ErrorCode.KILL_SWITCH_ACTIVE,
                f"This strategy cannot run: the deployment is not servable "
                f"(status={deployment.status}, lifecycle_state={deployment.lifecycle_state}).",
            )

    def assert_gate_passes(self, actor: User, deployment: AgentDeployment) -> None:
        """M3-3.6-FR-011/FR-021 -- fail closed on BLOCK, reusing Phase 3.3's
        single evaluation path. Distinct from ``DEPLOYMENT_PREFLIGHT_BLOCKED``
        (which 3.1 raises when a deployment cannot *reach* ACTIVE): this one
        stops an already-active deployment from taking over traffic, which is a
        different operator decision with a different remedy."""
        result = ReleaseGateService(self.db).evaluate(actor, deployment)
        if result.verdict == "BLOCK":
            blocking = ", ".join(
                finding["code"] for finding in result.findings
                if finding.get("severity") == "BLOCK"
            )
            raise IdentityError(
                ErrorCode.STRATEGY_GATE_BLOCKED,
                f"The release gate blocked this strategy operation: {blocking}. "
                f"See GET .../deployments/{deployment.id}/preflight for the full findings.",
            )

    def serving_deployment_other_than(self, deployment: AgentDeployment) -> AgentDeployment | None:
        """The servable deployment this one would take traffic from -- newest
        first, matching the ordering 3.4's resolver already uses."""
        return self.db.execute(
            select(AgentDeployment)
            .where(AgentDeployment.organization_id == deployment.organization_id,
                   AgentDeployment.agent_id == deployment.agent_id,
                   AgentDeployment.environment_id == deployment.environment_id,
                   AgentDeployment.id != deployment.id,
                   AgentDeployment.agent_version_id != deployment.agent_version_id,
                   servable_clause())
            .order_by(AgentDeployment.deployed_at.desc().nullslast(), AgentDeployment.id)
        ).scalars().first()

    # ------------------------------------------------------------------ #
    # The one way traffic moves (M3-3.6-FR-003, AC-08)
    # ------------------------------------------------------------------ #
    def apply_weights(self, actor: User, agent: Agent, environment: Environment, *,
                     candidate_version_id: uuid.UUID, candidate_weight: int,
                     other_version_id: uuid.UUID | None, other_weight: int,
                     reason: str) -> int:
        """Every weight change in this module goes through here, and this goes
        through Phase 3.4's ``set_weights`` -- atomic, revisioned,
        eligibility-checked, audited as ``DEPLOYMENT_TRAFFIC_CHANGED``. Nothing
        here validates weights or writes weight rows; 3.4 owns both.

        A 3.4 optimistic-concurrency loss is re-raised as ``STRATEGY_CONFLICT``
        so the caller sees a failure in the vocabulary of the operation they
        actually invoked, with 3.4's own reason preserved in the message."""
        entries = [{"agent_version_id": candidate_version_id, "weight": candidate_weight}]
        if other_version_id is not None:
            entries.append({"agent_version_id": other_version_id, "weight": other_weight})
        elif candidate_weight != 100:
            raise IdentityError(
                ErrorCode.STRATEGY_CONFLICT,
                "There is no other version to hold the remaining traffic, so the candidate "
                "must take 100%.",
            )

        try:
            result, _replayed = TrafficAllocationService(self.db).set_weights(
                actor, agent, environment, entries, reason=reason)
        except IdentityError as exc:
            if str(exc.code) == ErrorCode.TRAFFIC_ALLOCATION_CONFLICT:
                raise IdentityError(
                    ErrorCode.STRATEGY_CONFLICT,
                    "This agent's traffic was changed by another request while this strategy "
                    f"operation was running; reload and retry. ({exc.message})",
                ) from None
            raise
        return int(result["revision"])

    def record(self, actor: User, deployment: AgentDeployment,
              event: AuthorizationAuditEvent, meta: dict) -> None:
        _record_event(self.db, event, actor, organization_id=deployment.organization_id,
                     agent_id=deployment.agent_id, deployment_id=deployment.id,
                     meta={"deployment_id": str(deployment.id), **meta})

    # ------------------------------------------------------------------ #
    # The dispatching entry point (M3-3.6-FR-001)
    # ------------------------------------------------------------------ #
    def execute(self, actor: User, deployment_id: uuid.UUID, *,
               idempotency_key: str | None = None) -> dict:
        deployment = self.get_or_404(actor, deployment_id)

        def _do() -> dict:
            handler = handler_for(deployment.deployment_strategy)
            outcome = handler.execute(self, actor, deployment)
            self._commit()
            return outcome.as_dict()

        result, _replayed = IdempotencyService(self.db).execute(
            organization_id=actor.organization_id, operation="deployment.strategy.execute",
            key=idempotency_key, payload={"deployment_id": str(deployment_id)}, fn=_do,
        )
        return result

    # ------------------------------------------------------------------ #
    # Blue-green switch and rollback
    # ------------------------------------------------------------------ #
    def _current_weights(self, deployment: AgentDeployment) -> dict[uuid.UUID, int]:
        traffic = TrafficAllocationService(self.db)
        allocation = traffic.current(deployment.organization_id, deployment.agent_id,
                                    deployment.environment_id)
        if allocation is None:
            return {}
        return {w.agent_version_id: w.weight for w in traffic.weights_for(allocation.id)}

    def blue_green_switch(self, actor: User, deployment_id: uuid.UUID, *,
                         idempotency_key: str | None = None) -> dict:
        """M3-3.6-FR-022/023 -- the atomic switch, and blue preservation.

        One ``set_weights`` call moves BLUE 100→0 and GREEN 0→100 in a single
        allocation revision, so there is no committed interval in which both
        serve (FR-022). BLUE is then *kept* -- lifecycle-ACTIVE, zero-weight,
        recorded as GREEN's ``rollback_target_id`` -- which is the whole point
        of blue-green and the difference from RECREATE."""
        deployment = self.get_or_404(actor, deployment_id)

        def _do() -> dict:
            if deployment.deployment_strategy != "BLUE_GREEN":
                raise IdentityError(
                    ErrorCode.VALIDATION_ERROR,
                    f"This deployment's strategy is {deployment.deployment_strategy}, not "
                    "BLUE_GREEN.",
                )
            agent, environment = self.scope_for(deployment)
            self.assert_not_vetoed(agent, deployment)

            weights = self._current_weights(deployment)
            green_id = deployment.agent_version_id
            if green_id not in weights:
                raise IdentityError(
                    ErrorCode.BLUE_GREEN_NOT_PREPARED,
                    "GREEN has not been prepared: it holds no entry in the current traffic "
                    "allocation. Call the strategy execute (prepare) operation first, which "
                    "warms GREEN at 0% while BLUE keeps serving.",
                )
            blue_id = next((vid for vid, weight in weights.items()
                           if vid != green_id and weight > 0), None)
            if blue_id is None:
                raise IdentityError(
                    ErrorCode.BLUE_GREEN_NOT_PREPARED,
                    "There is no BLUE version currently serving traffic to switch away from.",
                )

            # The gate runs again at the switch, not only at prepare: a
            # deployment can pass validation and then have its agent killed,
            # its version revoked, or its signature invalidated before anyone
            # presses the button. Re-checking is the whole value of a gate.
            self.assert_gate_passes(actor, deployment)

            revision = self.apply_weights(
                actor, agent, environment,
                candidate_version_id=green_id, candidate_weight=100,
                other_version_id=blue_id, other_weight=0,
                reason=f"BLUE_GREEN switch: GREEN {green_id} to 100%, BLUE {blue_id} preserved at 0%.",
            )

            # Blue preservation, through the existing lineage authority rather
            # than a raw column write -- it validates same-agent and
            # rollback-eligible status for us.
            green_version = self.db.get(AgentVersion, green_id)
            VersionLineageService(self.db).set_rollback_target(green_version, blue_id)

            self.record(actor, deployment, AuthorizationAuditEvent.DEPLOYMENT_SUCCEEDED,
                       {"strategy": "BLUE_GREEN", "operation": "switch",
                        "blue_version_id": str(blue_id), "green_version_id": str(green_id),
                        "blue_preserved_as_rollback_target": True})
            self._commit()
            return StrategyOutcome(
                strategy="BLUE_GREEN", operation="switch", deployment_id=str(deployment.id),
                candidate_version_id=str(green_id), previous_version_id=str(blue_id),
                candidate_weight=100, previous_weight=0, allocation_revision=revision,
                detail=("GREEN now serves 100%. BLUE is preserved at 0% -- still deployed and "
                       "instantly returnable -- and recorded as GREEN's rollback target."),
            ).as_dict()

        result, _replayed = IdempotencyService(self.db).execute(
            organization_id=actor.organization_id, operation="deployment.strategy.bluegreen.switch",
            key=idempotency_key, payload={"deployment_id": str(deployment_id)}, fn=_do,
        )
        return result

    def blue_green_rollback(self, actor: User, deployment_id: uuid.UUID, *,
                           idempotency_key: str | None = None) -> dict:
        """M3-3.6-FR-024 -- return traffic to BLUE atomically.

        This is the operation; Phase 3.7 adds the *policy* that decides when to
        call it automatically. Deliberately does **not** check the §12 veto:
        rolling back reduces the candidate's exposure, and a kill switch must
        never be able to trap an operator on a version they are trying to leave.
        The gate is likewise not re-run -- BLUE is the version that was already
        serving, and demanding it re-pass a gate before it can be returned to
        would make rollback fail exactly when it is most needed."""
        deployment = self.get_or_404(actor, deployment_id)

        def _do() -> dict:
            agent, environment = self.scope_for(deployment)
            green_id = deployment.agent_version_id
            green_version = self.db.get(AgentVersion, green_id)
            blue_id = green_version.rollback_target_id if green_version else None
            if blue_id is None:
                raise IdentityError(
                    ErrorCode.BLUE_GREEN_NOT_PREPARED,
                    "This version has no preserved BLUE rollback target, so there is nothing "
                    "to roll back to. A rollback target is recorded by a blue-green switch.",
                )

            self.record(actor, deployment, AuthorizationAuditEvent.DEPLOYMENT_ROLLBACK_STARTED,
                       {"strategy": "BLUE_GREEN", "operation": "rollback",
                        "from_version_id": str(green_id), "to_version_id": str(blue_id)})
            revision = self.apply_weights(
                actor, agent, environment,
                candidate_version_id=blue_id, candidate_weight=100,
                other_version_id=green_id, other_weight=0,
                reason=f"BLUE_GREEN rollback: traffic returned to BLUE {blue_id}.",
            )
            self.record(actor, deployment, AuthorizationAuditEvent.RUNTIME_ROLLBACK_COMPLETED,
                       {"strategy": "BLUE_GREEN", "operation": "rollback",
                        "restored_version_id": str(blue_id)})
            self._commit()
            return StrategyOutcome(
                strategy="BLUE_GREEN", operation="rollback", deployment_id=str(deployment.id),
                candidate_version_id=str(blue_id), previous_version_id=str(green_id),
                candidate_weight=100, previous_weight=0, allocation_revision=revision,
                detail="Traffic returned to BLUE; GREEN is preserved at 0%.",
            ).as_dict()

        result, _replayed = IdempotencyService(self.db).execute(
            organization_id=actor.organization_id,
            operation="deployment.strategy.bluegreen.rollback",
            key=idempotency_key, payload={"deployment_id": str(deployment_id)}, fn=_do,
        )
        return result

    def _commit(self) -> None:
        """``AgentDeployment`` and the lineage writes above ride the same
        ``version_id_col`` optimistic-concurrency guard Phase 3.1 established,
        which raises ``StaleDataError`` at the first flush that emits a stale
        row's UPDATE -- not only at the commit. Translated here so a real race
        surfaces as ``STRATEGY_CONFLICT`` rather than a 500."""
        try:
            self.db.commit()
        except StaleDataError:
            self.db.rollback()
            raise IdentityError(
                ErrorCode.STRATEGY_CONFLICT,
                "This deployment was modified by another request while the strategy operation "
                "was running; reload and retry.",
            ) from None
