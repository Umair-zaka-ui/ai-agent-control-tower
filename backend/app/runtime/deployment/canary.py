"""ACT-SRS-M3 §Phase-3.5 -- ``CanaryRolloutService``, the engine that drives
Phase 3.4's traffic allocation progressively and automatically.

3.4 built the allocation and the operation to *set* weights; this is the driver
it was built for. The single most important rule here, and the one every method
below obeys: **a stage advance changes traffic by calling
``TrafficAllocationService.set_weights``** -- 3.4's atomic, revisioned,
eligibility-checked, audited mechanism -- and never by touching
``deployment_traffic_weights`` directly. There is no ``DeploymentTrafficWeight``
import in this module, so the rule is structural rather than aspirational
(mechanically checked -- see ``tests/runtime/test_canary_rollout.py``).

``RolloutPlan.state`` is written in exactly one place, ``_transition`` below,
through the pure graph in ``app.runtime.deployment.rollout`` -- the same single
transition authority discipline Phase 3.1 established for
``AgentDeployment.lifecycle_state``.

**Kill-switch dominance (§12) is the sharpest safety rule in this phase.** Every
operation that could give the candidate *more* traffic -- start, advance,
resume, promote, and the automated evaluate-and-advance -- calls
``_assert_not_vetoed`` first, which reads the exact fields Phase 3.4's resolver
reads. Operations that only ever *reduce* the candidate's exposure -- pause,
abort, request-rollback -- deliberately do **not**, because a kill switch must
never be able to trap a rollout in a state an operator cannot back out of. The
health engine independently refuses to return HEALTHY for a vetoed candidate
(``app.runtime.deployment.health``), so automation cannot reach a promotion
decision past a veto by two independent mechanisms rather than one.

**Interim auto-advance (M3-3.5-FR-013).** ``evaluate_and_advance`` is a bounded,
idempotent "evaluate health, advance if every gate is satisfied" operation. It
is *not* a scheduler and this phase does not build one: Phase 3.8 owns the real
distributed scheduler and will call this operation on a timer, exactly as
``app.integration.scheduler`` (Phase 2.1.3's own interim in-process
health-check loop) is documented to be replaced by it. Manual advance is always
available regardless."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.authorization.enums import AuthorizationAuditEvent
from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.runtime import (
    AgentDeployment,
    AgentVersion,
    Environment,
    RolloutPlan,
    RolloutStage,
)
from app.models.user import User
from app.runtime.deployment import rollout as rollout_machine
from app.runtime.deployment.health import HealthEvaluationService
from app.runtime.deployment.idempotency import IdempotencyService
from app.runtime.deployment.service import DeploymentLifecycleService
from app.runtime.deployment.traffic import TrafficAllocationService, is_servable
from app.runtime.services import _now, _record_event

# A stage's health window looks back at most this far even when the stage has
# been sitting open for hours: a canary that was healthy this morning and
# started failing ten minutes ago must not be rescued by the morning's good
# numbers. Bounded lookback keeps the verdict about the recent past.
MAX_HEALTH_WINDOW_SECONDS = 3600

_STATE_EVENT: dict[str, AuthorizationAuditEvent] = {
    "IN_PROGRESS": AuthorizationAuditEvent.DEPLOYMENT_ROLLOUT_STARTED,
    "PAUSED": AuthorizationAuditEvent.RUNTIME_DEPLOYMENT_PAUSED,
    "SUCCEEDED": AuthorizationAuditEvent.DEPLOYMENT_ROLLOUT_SUCCEEDED,
    "ABORTED": AuthorizationAuditEvent.DEPLOYMENT_ROLLOUT_ABORTED,
    "ROLLBACK_REQUESTED": AuthorizationAuditEvent.DEPLOYMENT_ROLLBACK_STARTED,
    "FAILED": AuthorizationAuditEvent.DEPLOYMENT_ROLLOUT_FAILED,
}


class CanaryRolloutService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Lookup
    # ------------------------------------------------------------------ #
    def get_or_404(self, actor: User, rollout_id: uuid.UUID) -> RolloutPlan:
        plan = self.db.get(RolloutPlan, rollout_id)
        if plan is None or plan.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.ROLLOUT_NOT_FOUND, "Rollout not found.")
        return plan

    def stages(self, plan: RolloutPlan) -> list[RolloutStage]:
        return list(self.db.execute(
            select(RolloutStage)
            .where(RolloutStage.rollout_plan_id == plan.id)
            .order_by(RolloutStage.stage_index)
        ).scalars())

    def current_stage(self, plan: RolloutPlan) -> RolloutStage | None:
        return self.db.execute(
            select(RolloutStage).where(
                RolloutStage.rollout_plan_id == plan.id,
                RolloutStage.stage_index == plan.current_stage_index,
            )
        ).scalars().first()

    # ------------------------------------------------------------------ #
    # §12 -- the veto
    # ------------------------------------------------------------------ #
    def _assert_not_vetoed(self, plan: RolloutPlan) -> None:
        """Reads the same two fields Phase 3.4's ``servable_clause`` reads, so
        a rollout can never advance a candidate the execution gate would
        refuse to serve. ``KillSwitchService`` suspends the *agent* at AGENT
        scope and the *deployment's* ``status`` at ORGANIZATION/PROJECT/
        PLATFORM scope; both are covered."""
        agent = self.db.get(Agent, plan.agent_id)
        if agent is None or agent.lifecycle_status == "SUSPENDED":
            raise IdentityError(
                ErrorCode.ROLLOUT_HALTED_BY_KILL_SWITCH,
                "This rollout is halted: the agent is suspended (kill switch or lifecycle "
                "suspension). A rollout can never advance or promote a suspended agent.",
            )
        if agent.lifecycle_status != "ACTIVE":
            raise IdentityError(
                ErrorCode.ROLLOUT_HALTED_BY_KILL_SWITCH,
                f"This rollout is halted: the agent is {agent.lifecycle_status}, not ACTIVE.",
            )
        deployment = HealthEvaluationService(self.db).servable_deployment_for(
            plan.organization_id, plan.agent_id, plan.environment_id, plan.candidate_version_id)
        if deployment is None:
            raise IdentityError(
                ErrorCode.ROLLOUT_HALTED_BY_KILL_SWITCH,
                "This rollout is halted: the candidate version has no servable deployment in "
                "this environment (it may have been paused, superseded, retired, or suspended "
                "by the kill switch).",
            )

    # ------------------------------------------------------------------ #
    # The one transition authority
    # ------------------------------------------------------------------ #
    def _transition(self, actor: User, plan: RolloutPlan, to_state: str, *,
                   reason: str | None = None, meta: dict | None = None) -> RolloutPlan:
        from_state = plan.state
        if not rollout_machine.can_transition(from_state, to_state):
            raise IdentityError(
                ErrorCode.ROLLOUT_INVALID_TRANSITION,
                f"Cannot move rollout from {from_state} to {to_state}.",
            )
        plan.state = to_state
        plan.state_reason = reason
        event = _STATE_EVENT.get(to_state, AuthorizationAuditEvent.DEPLOYMENT_STAGE_ADVANCED)
        try:
            # ``RolloutPlan.__mapper_args__["version_id_col"]`` puts
            # ``WHERE revision = <loaded value>`` on the UPDATE, so a second
            # actor racing this one loses at the database rather than by
            # timing. As in Phase 3.1's own lifecycle service, the whole
            # sequence through the commit is one try block -- SQLAlchemy can
            # raise ``StaleDataError`` at the first flush, which the audit
            # insert below can trigger, not only at the commit.
            _record_event(self.db, event, actor, organization_id=plan.organization_id,
                         agent_id=plan.agent_id, severity="INFO",
                         meta={"rollout_id": str(plan.id), "from": from_state, "to": to_state,
                              "reason": reason, **(meta or {})})
            self.db.commit()
        except StaleDataError:
            self.db.rollback()
            raise IdentityError(
                ErrorCode.ROLLOUT_CONFLICT,
                "This rollout was modified by another request; reload and retry.",
            ) from None
        self.db.refresh(plan)
        return plan

    # ------------------------------------------------------------------ #
    # Driving Phase 3.4's allocation (AC-02) -- the only way traffic moves
    # ------------------------------------------------------------------ #
    def _apply_candidate_weight(self, actor: User, plan: RolloutPlan, candidate_weight: int, *,
                               reason: str) -> None:
        """Set the candidate to ``candidate_weight`` and the stable version to
        the remainder, through 3.4's ``set_weights``.

        Every guarantee that matters here belongs to 3.4 and is inherited
        rather than reimplemented: the weights are validated to total exactly
        100, each version is checked eligible (published, signed, backed by a
        servable deployment in this environment), the change is written as a
        new allocation revision, the previous revision is retired in the same
        transaction, and the whole thing is audited as
        ``DEPLOYMENT_TRAFFIC_CHANGED``. This method contributes nothing to
        that except the numbers."""
        agent = self.db.get(Agent, plan.agent_id)
        environment = self.db.get(Environment, plan.environment_id)
        entries = [{"agent_version_id": plan.candidate_version_id, "weight": candidate_weight}]
        if plan.stable_version_id is not None and candidate_weight < 100:
            entries.append({"agent_version_id": plan.stable_version_id,
                           "weight": 100 - candidate_weight})
        elif plan.stable_version_id is not None:
            # At 100% the stable version stays in the allocation at zero
            # weight rather than vanishing from it: 3.4's resolver skips
            # zero-weight entries, and keeping the row makes the allocation
            # revision an explicit record that stable was taken to nothing --
            # which is exactly what a rollback needs to read.
            entries.append({"agent_version_id": plan.stable_version_id, "weight": 0})
        TrafficAllocationService(self.db).set_weights(
            actor, agent, environment, entries, reason=reason)

    # ------------------------------------------------------------------ #
    # Create + start (AC-01)
    # ------------------------------------------------------------------ #
    def create(self, actor: User, agent_id: uuid.UUID, environment_id: uuid.UUID,
              payload: dict, *, idempotency_key: str | None = None) -> tuple[dict, bool]:
        from app.runtime.schemas import RolloutPlanRead  # leaf module

        def _do() -> dict:
            traffic = TrafficAllocationService(self.db)
            agent, environment = traffic.resolve_scope(actor, agent_id, environment_id)

            candidate_id = payload["candidate_version_id"]
            candidate = self.db.get(AgentVersion, candidate_id)
            if candidate is None or candidate.agent_id != agent.id:
                raise IdentityError(ErrorCode.VERSION_NOT_ELIGIBLE,
                                   "The candidate version does not belong to this agent.")

            stable_id = payload.get("stable_version_id") or self._infer_stable_version(
                agent, environment, candidate_id)
            stages = payload["stages"]
            self._validate_stages(stages, stable_id)

            plan = RolloutPlan(
                organization_id=actor.organization_id, agent_id=agent.id,
                environment_id=environment.id, candidate_version_id=candidate_id,
                stable_version_id=stable_id, state="PENDING", current_stage_index=0,
                created_by=actor.id,
            )
            self.db.add(plan)
            self.db.flush()
            for index, stage in enumerate(stages):
                self.db.add(RolloutStage(
                    rollout_plan_id=plan.id, stage_index=index,
                    target_weight=stage["target_weight"],
                    min_duration_seconds=stage.get("min_duration_seconds", 0),
                    min_samples=stage.get("min_samples", 0),
                    health_requirement=stage.get("health_requirement", "HEALTHY"),
                    advance_mode=stage.get("advance_mode", "MANUAL"),
                ))
            self.db.commit()
            self.db.refresh(plan)

            if payload.get("start", True):
                plan = self._start(actor, plan)
            return self.read_model(plan)

        return IdempotencyService(self.db).execute(
            organization_id=actor.organization_id, operation="deployment.rollout.create",
            key=idempotency_key,
            payload={"agent_id": str(agent_id), "environment_id": str(environment_id),
                    "candidate_version_id": str(payload["candidate_version_id"]),
                    "stages": payload["stages"]},
            fn=_do,
        )

    def _infer_stable_version(self, agent: Agent, environment: Environment,
                             candidate_id: uuid.UUID) -> uuid.UUID | None:
        """The version currently carrying the most traffic that is not the
        candidate -- read from 3.4's own current allocation, falling back to
        the newest servable deployment's version when no allocation exists
        (3.4's implicit-100% case)."""
        traffic = TrafficAllocationService(self.db)
        allocation = traffic.current(agent.organization_id, agent.id, environment.id)
        if allocation is not None:
            weights = [w for w in traffic.weights_for(allocation.id)
                      if w.agent_version_id != candidate_id and w.weight > 0]
            if weights:
                return max(weights, key=lambda w: w.weight).agent_version_id
        deployment = self.db.execute(
            select(AgentDeployment)
            .where(AgentDeployment.organization_id == agent.organization_id,
                   AgentDeployment.agent_id == agent.id,
                   AgentDeployment.environment_id == environment.id,
                   AgentDeployment.agent_version_id != candidate_id)
            .order_by(AgentDeployment.deployed_at.desc().nullslast(), AgentDeployment.id)
        ).scalars().first()
        return deployment.agent_version_id if deployment is not None else None

    @staticmethod
    def _validate_stages(stages: list[dict], stable_id: uuid.UUID | None) -> None:
        if not stages:
            raise IdentityError(ErrorCode.VALIDATION_ERROR,
                               "A rollout plan must declare at least one stage.")
        weights = [s["target_weight"] for s in stages]
        if any(w < 0 or w > 100 for w in weights):
            raise IdentityError(ErrorCode.VALIDATION_ERROR,
                               "Every stage target weight must be between 0 and 100.")
        if weights != sorted(weights):
            raise IdentityError(
                ErrorCode.VALIDATION_ERROR,
                "Stage target weights must be non-decreasing: a canary promotes a candidate "
                "progressively, it does not step backwards.",
            )
        valid_requirements = {"HEALTHY", "DEGRADED", "UNHEALTHY",
                             rollout_machine.HEALTH_REQUIREMENT_NONE}
        for stage in stages:
            requirement = stage.get("health_requirement", "HEALTHY")
            if requirement in rollout_machine.NON_PROVING_HEALTH_STATES:
                raise IdentityError(
                    ErrorCode.VALIDATION_ERROR,
                    f"{requirement} cannot be a health requirement: it is the absence of "
                    "evidence, so a stage requiring it could never be satisfied. Use "
                    "health_requirement=NONE to waive the health gate explicitly.",
                )
            if requirement not in valid_requirements:
                raise IdentityError(
                    ErrorCode.VALIDATION_ERROR,
                    f"Unknown health_requirement {requirement!r}; expected one of "
                    f"{sorted(valid_requirements)}.",
                )
            if stage.get("advance_mode", "MANUAL") not in ("MANUAL", "AUTO"):
                raise IdentityError(ErrorCode.VALIDATION_ERROR,
                                   "advance_mode must be MANUAL or AUTO.")
        # A staged canary needs somewhere for the other 95% to go. 3.4's
        # weights must total exactly 100, so a candidate at any weight below
        # 100 is literally unrepresentable without a stable version. Rejected
        # explicitly here rather than failing later inside 3.4 with a
        # confusing weights error -- see this module's own docstring.
        if stable_id is None and any(w < 100 for w in weights):
            raise IdentityError(
                ErrorCode.VALIDATION_ERROR,
                "This agent has no stable version in this environment to canary against, so "
                "only a single 100% stage is possible. Deploy a stable version first, or "
                "declare one stage at 100%.",
            )

    def _start(self, actor: User, plan: RolloutPlan) -> RolloutPlan:
        self._assert_not_vetoed(plan)
        stage = self.current_stage(plan)
        plan = self._transition(actor, plan, "IN_PROGRESS",
                               reason="Rollout started.",
                               meta={"stage_index": plan.current_stage_index})
        self._apply_candidate_weight(
            actor, plan, stage.target_weight,
            reason=f"Canary rollout {plan.id} stage {stage.stage_index} "
                  f"({stage.target_weight}% candidate).")
        stage.entered_at = _now()
        try:
            self.db.commit()
        except StaleDataError:
            self.db.rollback()
            raise IdentityError(
                ErrorCode.ROLLOUT_CONFLICT,
                "This rollout was modified by another request; reload and retry.",
            ) from None
        self.db.refresh(plan)
        return plan

    # ------------------------------------------------------------------ #
    # Stage gates + advance (AC-02, AC-03)
    # ------------------------------------------------------------------ #
    def evaluate_gates(self, plan: RolloutPlan, *, actor: User | None = None,
                      persist: bool = True) -> tuple[rollout_machine.StageGateResult, dict]:
        """Evaluate the current stage's three gates, persisting the health
        verdict that informed the decision (FR-023) so a stuck or advanced
        canary can always be explained after the fact."""
        stage = self.current_stage(plan)
        if stage is None:
            raise IdentityError(ErrorCode.ROLLOUT_INVALID_TRANSITION,
                               "This rollout has no current stage.")
        health_service = HealthEvaluationService(self.db)
        agent = self.db.get(Agent, plan.agent_id)
        environment = self.db.get(Environment, plan.environment_id)
        deployment = health_service.servable_deployment_for(
            plan.organization_id, plan.agent_id, plan.environment_id, plan.candidate_version_id)

        now = _now()
        window_start = stage.entered_at or plan.created_at
        floor = now - timedelta(seconds=MAX_HEALTH_WINDOW_SECONDS)
        window_start = max(window_start, floor)

        verdict = health_service.evaluate(
            organization_id=plan.organization_id, agent=agent,
            agent_version_id=plan.candidate_version_id,
            window_start=window_start, window_end=now, min_samples=stage.min_samples,
            environment=environment, baseline_version_id=plan.stable_version_id,
            deployment=deployment, require_servable=True,
        )
        if persist:
            health_service.persist(
                verdict, organization_id=plan.organization_id,
                agent_version_id=plan.candidate_version_id,
                deployment_id=deployment.id if deployment else None,
                rollout_plan_id=plan.id, evaluated_by=actor.id if actor else None)
            self.db.commit()

        gates = rollout_machine.evaluate_stage_gates(
            entered_at=stage.entered_at, now=now,
            min_duration_seconds=stage.min_duration_seconds,
            sample_count=verdict.metrics.sample_count, min_samples=stage.min_samples,
            health_state=verdict.state, health_requirement=stage.health_requirement,
        )
        return gates, {
            "health_state": verdict.state,
            "explanation": verdict.explanation,
            "metrics": verdict.metrics.as_dict(),
            "baseline": verdict.baseline,
            "window_start": window_start.isoformat(),
            "window_end": now.isoformat(),
        }

    def advance(self, actor: User, plan: RolloutPlan, *,
               idempotency_key: str | None = None, force_gates: bool = False) -> dict:
        def _do() -> dict:
            if plan.state != "IN_PROGRESS":
                raise IdentityError(
                    ErrorCode.ROLLOUT_INVALID_TRANSITION,
                    f"Cannot advance a rollout in state {plan.state}.")
            self._assert_not_vetoed(plan)

            gates, health = self.evaluate_gates(plan, actor=actor)
            if not gates.satisfied and not force_gates:
                raise IdentityError(
                    ErrorCode.ROLLOUT_STAGE_GATE_NOT_MET,
                    "This stage's gates are not satisfied: " + " ".join(gates.reasons),
                )
            return self._advance_one_stage(actor, plan, health=health, gates=gates)

        # The fingerprint carries the caller's *intent* only -- the rollout
        # id -- never server-side state like the current stage index. 3.1's
        # contract treats a changed payload under the same key as a genuinely
        # different request (IDEMPOTENCY_CONFLICT), so including a value this
        # very operation mutates would make every retry look like a new
        # request and defeat the deduplication entirely.
        result, _replayed = IdempotencyService(self.db).execute(
            organization_id=actor.organization_id, operation="deployment.rollout.advance",
            key=idempotency_key, payload={"rollout_id": str(plan.id)}, fn=_do,
        )
        return result

    def _advance_one_stage(self, actor: User, plan: RolloutPlan, *, health: dict,
                          gates: rollout_machine.StageGateResult) -> dict:
        stages = self.stages(plan)
        next_index = plan.current_stage_index + 1

        if next_index >= len(stages):
            # The last stage cleared -- the candidate takes all traffic and
            # the rollout succeeds.
            return self._complete(actor, plan, health=health)

        next_stage = stages[next_index]
        try:
            # The whole mutation sequence is inside the guard, not just the
            # commit: with a ``version_id_col`` mapper, SQLAlchemy raises
            # ``StaleDataError`` at the *first flush* that emits this row's
            # UPDATE -- and the audit insert below triggers exactly such a
            # flush. Guarding only the commit lets a raw StaleDataError escape
            # as a 500 under a real race. Same shape and same reason as
            # ``_transition`` above and Phase 3.1's own lifecycle service.
            #
            # The stage index is committed *before* any traffic moves, so the
            # loser of a race is rejected while the allocation is still
            # untouched -- a rollout can never half-advance.
            plan.current_stage_index = next_index
            _record_event(self.db, AuthorizationAuditEvent.DEPLOYMENT_STAGE_ADVANCED, actor,
                         organization_id=plan.organization_id, agent_id=plan.agent_id,
                         meta={"rollout_id": str(plan.id), "from_stage": next_index - 1,
                              "to_stage": next_index, "target_weight": next_stage.target_weight,
                              "health_state": health["health_state"],
                              "gates": gates.as_dict()})
            self.db.commit()
        except StaleDataError:
            self.db.rollback()
            raise IdentityError(
                ErrorCode.ROLLOUT_CONFLICT,
                "This rollout was modified by another request; reload and retry.",
            ) from None

        self._apply_candidate_weight(
            actor, plan, next_stage.target_weight,
            reason=f"Canary rollout {plan.id} stage {next_index} "
                  f"({next_stage.target_weight}% candidate).")
        next_stage.entered_at = _now()
        try:
            self.db.commit()
        except StaleDataError:
            self.db.rollback()
            raise IdentityError(
                ErrorCode.ROLLOUT_CONFLICT,
                "This rollout was modified by another request; reload and retry.",
            ) from None
        self.db.refresh(plan)
        return self.read_model(plan)

    def _complete(self, actor: User, plan: RolloutPlan, *, health: dict | None = None) -> dict:
        """Final stage cleared: candidate to 100%, stable superseded (AC-11)."""
        self._apply_candidate_weight(
            actor, plan, 100,
            reason=f"Canary rollout {plan.id} promoted the candidate to 100%.")
        self._supersede_stable_deployment(actor, plan)
        plan = self._transition(actor, plan, "SUCCEEDED",
                               reason="All stages cleared; candidate promoted to 100%.",
                               meta={"health": health} if health else None)
        return self.read_model(plan)

    def _supersede_stable_deployment(self, actor: User, plan: RolloutPlan) -> None:
        """Drive the *existing* 3.1 lifecycle authority to supersede the old
        stable deployment -- never a direct ``lifecycle_state`` write. Phase
        3.2 already drives this same ``ACTIVE|PAUSED -> SUPERSEDED`` edge for
        promotion; this is the same edge, reached from a canary instead."""
        if plan.stable_version_id is None:
            return
        candidate_deployment = HealthEvaluationService(self.db).servable_deployment_for(
            plan.organization_id, plan.agent_id, plan.environment_id, plan.candidate_version_id)
        stale = self.db.execute(select(AgentDeployment).where(
            AgentDeployment.organization_id == plan.organization_id,
            AgentDeployment.agent_id == plan.agent_id,
            AgentDeployment.environment_id == plan.environment_id,
            AgentDeployment.agent_version_id == plan.stable_version_id,
            AgentDeployment.lifecycle_state.in_(("ACTIVE", "PAUSED")),
        )).scalars().all()
        lifecycle = DeploymentLifecycleService(self.db)
        for deployment in stale:
            if candidate_deployment is not None:
                deployment.superseded_by_deployment_id = candidate_deployment.id
            lifecycle.transition(
                actor, deployment, "SUPERSEDED",
                reason=f"Superseded by canary rollout {plan.id}.")

    # ------------------------------------------------------------------ #
    # Interim auto-advance (AC-12, FR-013)
    # ------------------------------------------------------------------ #
    def evaluate_and_advance(self, actor: User, plan: RolloutPlan, *,
                            idempotency_key: str | None = None) -> dict:
        """Bounded and idempotent: evaluates the current stage once and
        advances by at most **one** stage, only if that stage is AUTO and every
        gate is satisfied. Never loops through several stages in a single call
        -- each stage's minimum duration is a real waiting period, and a call
        that advanced 5% -> 100% because all the gates happened to be clear
        would defeat the entire purpose of staging.

        Returns the plan plus a ``gate_evaluation`` block explaining what
        happened, so a caller that did *not* advance learns why. Interim until
        Phase 3.8: its scheduler will call exactly this method on a timer,
        with no change required here."""
        def _do() -> dict:
            if plan.state != "IN_PROGRESS":
                return {**self.read_model(plan),
                       "gate_evaluation": {"advanced": False,
                                          "reason": f"Rollout is {plan.state}, not IN_PROGRESS."}}
            try:
                self._assert_not_vetoed(plan)
            except IdentityError as exc:
                # A veto is reported, never raised, on the automated path: the
                # scheduler that will drive this in 3.8 sweeps many rollouts
                # and must not have one killed agent abort the whole sweep.
                # It still does not advance -- that is the point.
                return {**self.read_model(plan),
                       "gate_evaluation": {"advanced": False, "halted": True,
                                          "reason": str(exc.message)}}

            stage = self.current_stage(plan)
            gates, health = self.evaluate_gates(plan, actor=actor)
            if stage.advance_mode != "AUTO":
                return {**self.read_model(plan),
                       "gate_evaluation": {"advanced": False, "health": health,
                                          "gates": gates.as_dict(),
                                          "reason": "Stage advance_mode is MANUAL."}}
            if not gates.satisfied:
                return {**self.read_model(plan),
                       "gate_evaluation": {"advanced": False, "health": health,
                                          "gates": gates.as_dict(),
                                          "reason": "Stage gates not satisfied."}}
            advanced = self._advance_one_stage(actor, plan, health=health, gates=gates)
            return {**advanced,
                   "gate_evaluation": {"advanced": True, "health": health,
                                      "gates": gates.as_dict()}}

        result, _replayed = IdempotencyService(self.db).execute(
            organization_id=actor.organization_id, operation="deployment.rollout.evaluate",
            key=idempotency_key, payload={"rollout_id": str(plan.id)}, fn=_do,
        )
        return result

    # ------------------------------------------------------------------ #
    # Pause / resume / abort / promote / request-rollback
    # ------------------------------------------------------------------ #
    def pause(self, actor: User, plan: RolloutPlan, *, reason: str | None = None,
             idempotency_key: str | None = None) -> dict:
        # Deliberately no veto check: pausing only reduces exposure, and a
        # kill switch must never prevent an operator from stopping a rollout.
        return self._idempotent(actor, plan, "deployment.rollout.pause", idempotency_key,
                               lambda: self.read_model(self._transition(
                                   actor, plan, "PAUSED", reason=reason or "Paused by operator.")))

    def resume(self, actor: User, plan: RolloutPlan, *, reason: str | None = None,
              idempotency_key: str | None = None) -> dict:
        def _do() -> dict:
            self._assert_not_vetoed(plan)
            return self.read_model(self._transition(
                actor, plan, "IN_PROGRESS", reason=reason or "Resumed by operator."))
        return self._idempotent(actor, plan, "deployment.rollout.resume", idempotency_key, _do)

    def abort(self, actor: User, plan: RolloutPlan, *, reason: str | None = None,
             idempotency_key: str | None = None) -> dict:
        """AC-10 -- candidate to 0%, all traffic back to stable, atomically
        through 3.4's allocation mechanism. No veto check: aborting is the
        de-escalation an operator must always be able to reach, and it is
        precisely what someone does *after* hitting the kill switch."""
        def _do() -> dict:
            if plan.stable_version_id is not None:
                self._apply_candidate_weight(
                    actor, plan, 0,
                    reason=f"Canary rollout {plan.id} aborted; all traffic returned to stable.")
            return self.read_model(self._transition(
                actor, plan, "ABORTED", reason=reason or "Aborted by operator."))
        return self._idempotent(actor, plan, "deployment.rollout.abort", idempotency_key, _do)

    def request_rollback(self, actor: User, plan: RolloutPlan, *, reason: str | None = None,
                        idempotency_key: str | None = None) -> dict:
        """The terminal rollback *outcome* of a rollout: traffic returns to
        stable and the plan records that a rollback was asked for.

        The **3.5/3.7 seam**: this phase can request a rollback and react to a
        failing health gate by refusing to advance; the governed, configurable
        automatic *trigger policy* -- per-tenant rules like "roll back if the
        error rate exceeds X for Y minutes" -- is Phase 3.7, which will decide
        *when* to call this rather than reimplementing what it does."""
        def _do() -> dict:
            if plan.stable_version_id is not None:
                self._apply_candidate_weight(
                    actor, plan, 0,
                    reason=f"Canary rollout {plan.id} rollback requested; traffic to stable.")
            return self.read_model(self._transition(
                actor, plan, "ROLLBACK_REQUESTED",
                reason=reason or "Rollback requested."))
        return self._idempotent(actor, plan, "deployment.rollout.rollback", idempotency_key, _do)

    def promote(self, actor: User, plan: RolloutPlan, *, reason: str | None = None,
               idempotency_key: str | None = None) -> dict:
        """AC-11 -- jump straight to 100% and supersede stable. Still refuses a
        vetoed candidate: promotion is the largest possible traffic increase,
        so it is exactly what §12 must not allow past a kill switch."""
        def _do() -> dict:
            if plan.state != "IN_PROGRESS":
                raise IdentityError(ErrorCode.ROLLOUT_INVALID_TRANSITION,
                                   f"Cannot promote a rollout in state {plan.state}.")
            self._assert_not_vetoed(plan)
            stages = self.stages(plan)
            plan.current_stage_index = max(len(stages) - 1, 0)
            self.db.commit()
            return self._complete(actor, plan)
        return self._idempotent(actor, plan, "deployment.rollout.promote", idempotency_key, _do)

    def _idempotent(self, actor: User, plan: RolloutPlan, operation: str,
                   idempotency_key: str | None, fn) -> dict:
        result, _replayed = IdempotencyService(self.db).execute(
            organization_id=actor.organization_id, operation=operation, key=idempotency_key,
            payload={"rollout_id": str(plan.id)}, fn=fn,
        )
        return result

    # ------------------------------------------------------------------ #
    # Presentation
    # ------------------------------------------------------------------ #
    def read_model(self, plan: RolloutPlan) -> dict:
        """Returns a **JSON-safe** dict, not raw ORM values.

        Every operation here runs inside 3.1's ``IdempotencyService``, which
        stores whatever the operation returns verbatim in a JSONB
        ``result_ref`` so a replay can return it without re-running the work.
        A dict containing ``UUID``/``datetime`` objects fails at that INSERT,
        not at the API boundary -- so the serialization happens here, at the
        single place every operation's result is built. Same reason, and same
        ``model_dump(mode="json")`` shape, as Phase 3.4's
        ``TrafficAllocationService.set_weights``."""
        from app.runtime.schemas import RolloutPlanRead  # leaf module

        return RolloutPlanRead.model_validate(self._plan_dict(plan)).model_dump(mode="json")

    def _plan_dict(self, plan: RolloutPlan) -> dict:
        return {
            "id": plan.id,
            "organization_id": plan.organization_id,
            "agent_id": plan.agent_id,
            "environment_id": plan.environment_id,
            "candidate_version_id": plan.candidate_version_id,
            "stable_version_id": plan.stable_version_id,
            "state": plan.state,
            "current_stage_index": plan.current_stage_index,
            "state_reason": plan.state_reason,
            "revision": plan.revision,
            "created_at": plan.created_at,
            "updated_at": plan.updated_at,
            "created_by": plan.created_by,
            "stages": [
                {
                    "id": stage.id,
                    "stage_index": stage.stage_index,
                    "target_weight": stage.target_weight,
                    "min_duration_seconds": stage.min_duration_seconds,
                    "min_samples": stage.min_samples,
                    "health_requirement": stage.health_requirement,
                    "advance_mode": stage.advance_mode,
                    "entered_at": stage.entered_at,
                }
                for stage in self.stages(plan)
            ],
        }
