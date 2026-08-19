"""ACT-SRS-M3 §Phase-3.9 (M3-3.9-FR-030..033) -- ROLLING deployment, over the
real worker fleet. This module resolves ruling #1.

Phase 3.6 declared ROLLING and refused to implement it, and the refusal was
correct: rolling means "convert the fleet a piece at a time", and there was no
fleet. The two vestigial instance-count columns on ``agent_deployments`` were
the only thing that looked like one, and nothing reads them to make any
decision, so a handler built on them would have reported progress while
nothing rolled. Phase 3.9 builds the fleet, so rolling can finally be defined
over something real.

**What a cohort is here.** A cohort is a declared, labelled partition of the
registered worker fleet (``worker_registrations.cohort``). Its *capacity* is
the sum of the declared concurrency of its live, currently-heartbeating
workers. That number is real: it is how many executions those processes can
actually run at once, reported by the processes themselves.

**What rolls, precisely.** A rolling deployment converts the fleet cohort by
cohort, and each step moves the candidate's traffic share to the fraction of
total fleet capacity converted so far. A fleet of two cohorts holding 8 and 2
slots produces steps of **80% and 100%** -- not 25/50/75/100, not any other
invented ladder. Four equal cohorts produce 25/50/75/100 because the fleet
*is* four equal quarters. The shape of the rollout is dictated by the shape of
the fleet, which is the entire difference between this and a canary, and the
entire reason it could not be written before now.

**The honest limit, stated up front rather than discovered later.** Workers
are **not** version-pinned. An execution's version is chosen at enqueue time
by Phase 3.4's resolver and written onto the execution row; any worker may run
any execution it claims. So what a rolling step shifts is the *share of new
work routed to the candidate*, in units of real fleet capacity -- it does not
make cohort A's processes exclusively serve the new version.

That limit is deliberate, not an omission. Pinning workers to versions would
mean the claim path second-guessing 3.4's routing decision, which is 3.4's
sole authority, and would starve any execution whose version had no converted
worker yet. The design keeps one allocator and makes the fleet the thing that
*sizes and gates* the rollout:

- **Sizing** -- step weights are computed from live capacity, so a step can
  never describe capacity that does not exist.
- **Gating** -- before each step, the cohort it names must still be present
  and heartbeating. A rolling deployment cannot advance over a cohort that
  died mid-rollout; it fails closed with ``ROLLING_COHORT_INVALID`` rather
  than quietly promoting traffic onto capacity that has gone away.

Neither is expressible without a real fleet, and both are things a counter on
a deployment row could never have done.

**Why there is no rolling state machine.** Phase 3.5 already built one --
seven states, pause, resume, abort, rollback-request, per-stage health gates,
optimistic concurrency, idempotency, audit. Rolling needs exactly that machine
and differs only in where the stage weights come from. So a rolling deployment
*is* a ``RolloutPlan``, with ``kind='ROLLING'`` and stages derived here, and
every subsequent operation -- advance, pause, resume, abort, request rollback
-- is Phase 3.5's, unmodified. Rollback integration (M3-3.9-FR-033) is
inherited the same way: 3.7's rollback acts on the deployment, and a rolling
plan's ``ROLLBACK_REQUESTED`` state is the same state 3.7 already understands.

(The instance-count columns are named only indirectly here, deliberately.
Phase 3.1's mechanically-enforced test asserts their names appear nowhere in
this package, prose included -- a stricter guard than "do not assign to them",
and one this module keeps rather than relaxes.)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.errors import ErrorCode, IdentityError
from app.models.runtime import AgentDeployment, AgentVersion, RolloutPlan, RolloutStage
from app.models.user import User
from app.runtime.deployment.canary import CanaryRolloutService
from app.runtime.deployment.idempotency import IdempotencyService
from app.runtime.deployment.rollout import TERMINAL_STATES
from app.runtime.deployment.strategies import DeploymentStrategyService
from app.workers.fleet import WorkerFleetService


@dataclass(frozen=True, slots=True)
class CohortStep:
    """One cohort's conversion, and the traffic share it represents."""

    cohort: str
    capacity: int
    cumulative_capacity: int
    total_capacity: int
    target_weight: int

    def as_dict(self) -> dict:
        return {
            "cohort": self.cohort,
            "capacity": self.capacity,
            "cumulative_capacity": self.cumulative_capacity,
            "total_capacity": self.total_capacity,
            "target_weight": self.target_weight,
        }


def derive_cohort_steps(capacity_by_cohort: dict[str, int]) -> list[CohortStep]:
    """Turn live fleet capacity into the rollout's steps. Pure -- no I/O, no
    clock, no database -- so the arithmetic that decides how much production
    traffic moves is exhaustively testable without standing up a fleet.

    Cohorts are converted in name order. The ordering has to be *some*
    deterministic thing, and a name is the one an operator can predict and
    control (name them ``01-canary``, ``02-rest`` and they convert in that
    order); ordering by capacity or by registration time would make the
    rollout's shape depend on which machine happened to boot first.

    The final step is pinned to exactly 100 rather than left to rounding.
    Integer weights over three cohorts of equal size round to 33/67/100 only
    if the last one is forced; without that pin a rollout could finish at 99%
    and leave the old version quietly serving one request in a hundred
    forever, which is the kind of ending nobody notices until it matters."""
    if not capacity_by_cohort:
        raise IdentityError(
            ErrorCode.ROLLING_COHORT_INVALID,
            "No live execution workers are registered, so there is no fleet to roll over. "
            "A rolling deployment shifts capacity across real worker cohorts; with no "
            "workers it would be a progress bar over nothing. Start workers "
            "(python -m app.workers.runner), or use RECREATE for a direct cutover.",
        )
    total = sum(capacity_by_cohort.values())
    if total <= 0:  # pragma: no cover -- concurrency > 0 is a CHECK constraint
        raise IdentityError(
            ErrorCode.ROLLING_COHORT_INVALID,
            "The registered fleet reports zero total capacity.",
        )
    steps: list[CohortStep] = []
    cumulative = 0
    names = sorted(capacity_by_cohort)
    for index, cohort in enumerate(names):
        capacity = capacity_by_cohort[cohort]
        cumulative += capacity
        weight = 100 if index == len(names) - 1 else round(cumulative * 100 / total)
        # Never step backwards and never stall: rounding can otherwise
        # produce a repeated weight for two very small cohorts, and a step
        # that moves no traffic is a step that cannot be observed to have
        # happened.
        if steps and weight <= steps[-1].target_weight:
            weight = min(100, steps[-1].target_weight + 1)
        steps.append(CohortStep(cohort=cohort, capacity=capacity,
                                cumulative_capacity=cumulative, total_capacity=total,
                                target_weight=weight))
    return steps


class RollingDeploymentService:
    """M3-3.9-FR-030..033. Creation and cohort re-validation live here;
    everything else is Phase 3.5's rollout engine."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ----------------------------------------------------------------- #
    def fleet_steps(self) -> list[CohortStep]:
        return derive_cohort_steps(WorkerFleetService(self.db).capacity_by_cohort())

    def active_plan_for(self, deployment: AgentDeployment) -> RolloutPlan | None:
        """Any non-terminal plan already governing this (agent, environment).

        Rolling refuses to start alongside one. Two plans moving the same
        allocation would each keep setting weights the other did not expect,
        and 3.4's last-write-wins revisioning would faithfully record the
        resulting mess. Canary does not make this check because 3.5 predates
        a second plan kind existing; adding it here is stricter than what came
        before and does not relax anything."""
        return self.db.execute(
            select(RolloutPlan).where(
                RolloutPlan.organization_id == deployment.organization_id,
                RolloutPlan.agent_id == deployment.agent_id,
                RolloutPlan.environment_id == deployment.environment_id,
                RolloutPlan.state.not_in(tuple(TERMINAL_STATES)),
            ).order_by(RolloutPlan.created_at.desc())
        ).scalars().first()

    def start(self, actor: User, deployment: AgentDeployment, *,
              payload: dict | None = None,
              idempotency_key: str | None = None) -> tuple[dict, bool]:
        """Begin a rolling conversion of the fleet to this deployment's
        version.

        Order of checks is load-bearing and mirrors every other strategy in
        this package: scope, then the §12 veto, then the release gate, then
        the fleet. The veto comes before the gate because a suspended agent
        must be refused for the reason it was suspended, not for whatever the
        gate happens to say about it; the fleet comes last because it is the
        only check whose answer changes second to second, and an operator
        should not be told "no workers" when the real problem is that their
        release is blocked."""
        options = payload or {}

        def _do() -> dict:
            canary = CanaryRolloutService(self.db)
            strategies = DeploymentStrategyService(self.db)
            agent, environment = strategies.scope_for(deployment)
            strategies.assert_not_vetoed(agent, deployment)
            strategies.assert_gate_passes(actor, deployment)

            existing = self.active_plan_for(deployment)
            if existing is not None:
                raise IdentityError(
                    ErrorCode.ROLLOUT_CONFLICT,
                    f"A {existing.kind} rollout ({existing.id}) is already {existing.state} for "
                    "this agent and environment. Finish, abort or roll it back before starting "
                    "a rolling deployment -- two plans moving one allocation would fight.",
                )

            candidate_id = deployment.agent_version_id
            candidate = self.db.get(AgentVersion, candidate_id)
            if candidate is None or candidate.agent_id != agent.id:
                raise IdentityError(ErrorCode.VERSION_NOT_ELIGIBLE,
                                    "The deployment's version does not belong to this agent.")
            stable_id = options.get("stable_version_id") or canary._infer_stable_version(
                agent, environment, candidate_id)

            steps = self.fleet_steps()
            stage_dicts = [{
                "target_weight": step.target_weight,
                "min_duration_seconds": options.get("min_duration_seconds", 0),
                "min_samples": options.get("min_samples", 0),
                "health_requirement": options.get("health_requirement", "HEALTHY"),
                "advance_mode": options.get("advance_mode", "MANUAL"),
            } for step in steps]
            canary._validate_stages(stage_dicts, stable_id)

            plan = RolloutPlan(
                organization_id=actor.organization_id, agent_id=agent.id,
                environment_id=environment.id, candidate_version_id=candidate_id,
                stable_version_id=stable_id, kind="ROLLING", state="PENDING",
                current_stage_index=0, created_by=actor.id,
                cohort_plan={"deployment_id": str(deployment.id),
                             "total_capacity": steps[0].total_capacity,
                             "steps": [step.as_dict() for step in steps]},
            )
            self.db.add(plan)
            self.db.flush()
            for index, (step, stage) in enumerate(zip(steps, stage_dicts, strict=True)):
                self.db.add(RolloutStage(
                    rollout_plan_id=plan.id, stage_index=index,
                    target_weight=step.target_weight,
                    min_duration_seconds=stage["min_duration_seconds"],
                    min_samples=stage["min_samples"],
                    health_requirement=stage["health_requirement"],
                    advance_mode=stage["advance_mode"],
                ))
            self.db.commit()
            self.db.refresh(plan)

            if options.get("start", True):
                plan = canary._start(actor, plan)
            return self.read_model(plan)

        return IdempotencyService(self.db).execute(
            organization_id=actor.organization_id, operation="deployment.rolling.start",
            key=idempotency_key,
            payload={"deployment_id": str(deployment.id)},
            fn=_do,
        )

    # ----------------------------------------------------------------- #
    def assert_cohort_still_live(self, plan: RolloutPlan, stage_index: int) -> dict:
        """M3-3.9-FR-032 -- the step about to be taken must still describe
        real capacity.

        This is the gate that makes the fleet load-bearing rather than
        decorative. A rolling deployment derived its steps from the fleet as
        it was at creation; between then and now, machines fail. Advancing a
        step whose cohort has gone would promote traffic onto capacity that no
        longer exists, and would do it while reporting a tidy percentage.

        Fails closed. The remedy is an operator decision -- bring the cohort
        back, or abort the rollout -- and neither is one this code should make
        on its own."""
        plan_steps = ((plan.cohort_plan or {}).get("steps") or [])
        if stage_index >= len(plan_steps):
            raise IdentityError(
                ErrorCode.ROLLING_COHORT_INVALID,
                f"Rolling plan {plan.id} has no cohort recorded for stage {stage_index}.",
            )
        step = plan_steps[stage_index]
        live = WorkerFleetService(self.db).capacity_by_cohort()
        available = live.get(step["cohort"], 0)
        if available <= 0:
            raise IdentityError(
                ErrorCode.ROLLING_COHORT_INVALID,
                f"Cohort {step['cohort']!r} has no live workers, so this rolling step would "
                f"move traffic to {step['target_weight']}% of a fleet that is not there. "
                "Restore the cohort or abort the rollout.",
            )
        return {"cohort": step["cohort"], "planned_capacity": step["capacity"],
                "live_capacity": available, "target_weight": step["target_weight"]}

    def read_model(self, plan: RolloutPlan) -> dict:
        """Phase 3.5's read model, unchanged -- ``kind`` and ``cohort_plan``
        are carried by ``RolloutPlanRead`` itself, so a rolling plan and a
        canary plan serialize through exactly one code path."""
        return CanaryRolloutService(self.db).read_model(plan)

    def get_or_404(self, actor: User, plan_id: uuid.UUID) -> RolloutPlan:
        plan = CanaryRolloutService(self.db).get_or_404(actor, plan_id)
        if plan.kind != "ROLLING":
            raise IdentityError(
                ErrorCode.ROLLOUT_NOT_FOUND,
                f"Rollout {plan_id} is a {plan.kind} rollout, not a rolling deployment.",
            )
        return plan
