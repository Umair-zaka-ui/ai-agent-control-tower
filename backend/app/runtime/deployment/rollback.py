"""Phase 3.7 (ACT-SRS-M3 §Phase-3.7, §11, §12) -- automated rollback and
release safety.

Phases 3.5 and 3.6 gave this platform rollback *operations*: a canary can
request one, a blue-green deployment can return to BLUE. What neither gave it
was a **policy** -- the governed, per-tenant rules that decide when a rollback
should happen without a human watching a dashboard at 3am. That is this
module.

Three things are new here, and only three:

1. **``AgentVersion.rollback_target_id`` becomes authoritative.** It has
   existed since Phase 5.2 Part 1 and Phase 3.6 already reads it to perform a
   blue-green rollback, so "nothing reads it" is no longer true -- but nothing
   yet *designated* it as part of a rollout, and no other rollback path
   honoured it. Here it becomes the single answer to "where does a rollback
   go", for every trigger.
2. **A unified rollback operation** (``RollbackService.execute``) serving all
   four triggers -- MANUAL, REQUESTED, AUTOMATIC and FORCED -- rather than a
   fourth parallel implementation beside the three that already existed.
3. **A trigger policy engine** that reads Phase 3.5's health verdicts and
   decides whether a regression warrants acting.

**What this module deliberately does not do.** It computes no health of its
own -- ``HealthEvaluationService`` (3.5) is the only thing in this codebase
that judges whether a version is behaving, and a second opinion living here
would be a second definition of "unhealthy" to keep in sync. It writes no
traffic weights -- every move goes through Phase 3.4's
``TrafficAllocationService.set_weights``, atomic, revisioned and audited. And
it runs on no timer: ``evaluate`` is a bounded operation a caller invokes,
exactly as 3.5's auto-advance is, until Phase 3.8's scheduler drives it.

---

**Kill-switch dominance, and the one distinction that matters (§12).**

The rule is that *automation* is subordinate to a kill switch. It is not that
*rollback* is. Those are different statements and conflating them would make
the platform less safe, not more.

- An **automatic** rollback on a killed agent does not run. It records why and
  stops. Automation that "rolled back to a healthy version and reactivated it"
  would be automation quietly undoing a human's kill -- the single thing §12
  exists to prevent.
- A **manual** rollback on a killed agent still runs. This matches Phase 3.6's
  own reasoning exactly: rolling back reduces the candidate's exposure, and a
  kill switch must never trap an operator on the version they are trying to
  leave. An operator who hits the kill switch and then rolls back has made two
  deliberate decisions, and the platform should honour both.

Nothing here ever writes ``Agent.lifecycle_status`` or lifts a deployment's
suspension. A rollback moves traffic; clearing a kill is a human act, and the
absence of that write is asserted structurally by this phase's tests rather
than merely intended.

---

**Anti-flap.** A rollback that immediately re-triggers is worse than no
automation: it produces a version thrashing under a policy that cannot settle.
Two independent guards prevent it, and either alone would be insufficient:

- A **cooldown** (``RollbackTriggerPolicy.cooldown_seconds``, default 15
  minutes) measured from the most recent automatic rollback for the same
  (agent, environment). Within it, evaluation reports the crossing and
  declines to act.
- The **target is not re-evaluated as a candidate**. After a rollback the
  last-known-good is serving; it is the baseline, not something under trial.
  Automatic evaluation only ever considers a candidate that a rollout or a
  strategy put on trial, so the version a rollback restores cannot itself be
  rolled back by the same policy on the next tick.

---

**The recovery model (M3-3.7-FR-050).** Rollback intent is durable; evaluation
state is ephemeral. A ``RollbackEvent`` row is committed as ``IN_PROGRESS``
*before* any traffic moves and only marked ``COMPLETED`` after the allocation
commits, so a process dying between the two leaves a readable record of an
intent that was formed but not finished. ``resume_incomplete`` finds such rows
and completes them; because 3.4's allocation write is atomic and idempotent in
effect (setting the same weights again yields the same serving state), a
resumed rollback either finishes the move or confirms it already happened.
There is no half-applied state to repair, because the allocation never has
one. Health verdicts, threshold arithmetic and cooldown windows are all
recomputed from the database on demand and are deliberately kept nowhere --
they are exactly the ephemeral half of ``RECOVERY.md``'s split.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.authorization.enums import AuthorizationAuditEvent
from app.identity.errors import ErrorCode, IdentityError
from app.models.agent import Agent
from app.models.runtime import (
    AgentDeployment,
    AgentVersion,
    Environment,
    RollbackEvent,
    RollbackTriggerPolicy,
    RolloutPlan,
)
from app.models.user import User
from app.runtime.deployment.canary import CanaryRolloutService
from app.runtime.deployment.health import HealthEvaluationService
from app.runtime.deployment.idempotency import IdempotencyService
from app.runtime.deployment.traffic import TrafficAllocationService, is_servable
from app.runtime.environment.service import EnvironmentService
from app.runtime.services import _now, _record_event
from app.runtime.versioning.lineage import VersionLineageService

# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #
TRIGGERS: frozenset[str] = frozenset({"MANUAL", "REQUESTED", "AUTOMATIC", "FORCED"})
POLICY_MODES: frozenset[str] = frozenset({"AUTO_EXECUTE", "NOTIFY_ONLY"})

#: A rollback fires on evidence of harm. These two states are the absence of
#: evidence, not evidence of absence, and neither may ever trigger one.
#: ``INSUFFICIENT_DATA`` is Phase 3.5's first-class "we have not seen enough to
#: say" (M3-3.7-FR-023); ``UNKNOWN`` is what the health engine returns for a
#: vetoed or non-servable candidate, where automation must stand down rather
#: than act on a judgement it could not actually form.
NON_ACTIONABLE_HEALTH_STATES: frozenset[str] = frozenset({"UNKNOWN", "INSUFFICIENT_DATA"})

#: Deliberately *wider* than Phase 3.5's stage-gate thresholds. A canary stage
#: refusing to advance is cheap and reversible -- the candidate simply waits.
#: An automatic rollback is neither: it moves production traffic without a
#: human in the loop. The bar for acting unilaterally is therefore higher than
#: the bar for declining to promote, and these numbers say so.
DEFAULT_TRIGGER_THRESHOLDS: dict[str, float] = {
    # Absolute error rate on the candidate.
    "error_rate": 0.20,
    # Policy-denial surge -- distinct from errors: the version is running fine
    # and being refused, which usually means a configuration or permission
    # regression rather than a broken model.
    "denial_rate": 0.20,
    # Regression multipliers against the baseline (stable) version over the
    # same window. Absolute latency and cost limits are meaningless across
    # agents; a candidate being twice as slow as the version it replaces is
    # meaningful for all of them.
    "latency_regression_multiplier": 2.0,
    "cost_regression_multiplier": 2.0,
    # Whether a sustained UNHEALTHY verdict from 3.5 is itself sufficient,
    # independent of which individual number produced it.
    "rollback_on_unhealthy": 1.0,
}

DEFAULT_MIN_SAMPLES = 20
DEFAULT_COOLDOWN_SECONDS = 900
#: How far back health is aggregated when evaluating a trigger.
DEFAULT_WINDOW_SECONDS = 900


def thresholds_for_policy(policy: RollbackTriggerPolicy | None) -> dict[str, float]:
    """Policy overrides on top of the defaults, ignoring unknown keys and
    non-numeric values rather than failing -- a policy row is tenant-authored
    data, and a typo in it must not be able to take the safety system down."""
    resolved = dict(DEFAULT_TRIGGER_THRESHOLDS)
    if policy is None:
        return resolved
    for key, value in (policy.thresholds or {}).items():
        if key in resolved and isinstance(value, (int, float)) and not isinstance(value, bool):
            resolved[key] = float(value)
    return resolved


# --------------------------------------------------------------------------- #
# The pure decision (no I/O -- unit-testable without a database)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class TriggerDecision:
    """Why automation did or did not act. Every field exists so the answer can
    be explained afterwards: an automatic rollback nobody can account for is
    worse than none at all."""

    should_rollback: bool
    health_state: str
    reasons: tuple[str, ...]
    #: Set when a crossing was detected but acting was declined anyway --
    #: cooldown, NOTIFY_ONLY mode, or a kill switch. Distinct from
    #: ``should_rollback=False`` with no reasons, which means nothing was wrong.
    withheld_reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "should_rollback": self.should_rollback,
            "health_state": self.health_state,
            "reasons": list(self.reasons),
            "withheld_reason": self.withheld_reason,
        }


def evaluate_thresholds(health_state: str, metrics: dict, baseline: dict | None,
                        thresholds: dict[str, float], *, min_samples: int) -> TriggerDecision:
    """The trigger arithmetic, as a pure function.

    Order is deliberate and mirrors Phase 3.5's own health evaluation, for the
    same reasons: the cheapest disqualifying facts are checked first, and a
    candidate that cannot be judged is never judged.

    1. **Non-actionable verdict** -- UNKNOWN or INSUFFICIENT_DATA. Stop.
    2. **Sample floor** -- below it, stop, regardless of how bad the few
       samples look (M3-3.7-FR-023). Ten failures out of ten is a stronger
       signal than two out of two, and neither is twenty.
    3. **Thresholds** -- absolute first, then baseline-relative.
    """
    if health_state in NON_ACTIONABLE_HEALTH_STATES:
        return TriggerDecision(False, health_state, (),
                               withheld_reason=f"Health verdict {health_state} is not evidence "
                                               "of a regression; automation stands down.")

    sample_count = int(metrics.get("sample_count") or 0)
    if sample_count < min_samples:
        return TriggerDecision(
            False, health_state, (),
            withheld_reason=f"Only {sample_count} samples observed; {min_samples} required "
                            "before automation may act.")

    reasons: list[str] = []

    error_rate = float(metrics.get("error_rate") or 0.0)
    if error_rate >= thresholds["error_rate"]:
        reasons.append(f"error_rate {error_rate:.3f} >= {thresholds['error_rate']:.3f}")

    denial_rate = float(metrics.get("denial_rate") or 0.0)
    if denial_rate >= thresholds["denial_rate"]:
        reasons.append(f"denial_rate {denial_rate:.3f} >= {thresholds['denial_rate']:.3f}")

    if baseline:
        reasons.extend(_baseline_regressions(metrics, baseline, thresholds))

    if not reasons and health_state == "UNHEALTHY" and thresholds.get("rollback_on_unhealthy"):
        # 3.5 judged the candidate unhealthy on a signal this policy does not
        # name a number for. Deferring to that judgement is the point of
        # consuming its verdicts rather than recomputing them.
        reasons.append("health verdict UNHEALTHY")

    return TriggerDecision(bool(reasons), health_state, tuple(reasons))


def _baseline_regressions(metrics: dict, baseline: dict,
                          thresholds: dict[str, float]) -> list[str]:
    """Candidate-versus-stable comparisons. A zero or missing baseline value is
    skipped rather than treated as infinitely good -- dividing by it would
    manufacture a regression out of an absent measurement."""
    found: list[str] = []

    base_latency = baseline.get("p95_duration_ms") or baseline.get("avg_duration_ms")
    cand_latency = metrics.get("p95_duration_ms") or metrics.get("avg_duration_ms")
    if base_latency and cand_latency:
        limit = float(base_latency) * thresholds["latency_regression_multiplier"]
        if float(cand_latency) >= limit:
            found.append(f"latency {float(cand_latency):.0f}ms >= {limit:.0f}ms "
                         f"({thresholds['latency_regression_multiplier']}x baseline)")

    base_cost = baseline.get("total_cost")
    cand_cost = metrics.get("total_cost")
    base_samples = baseline.get("sample_count") or 0
    cand_samples = metrics.get("sample_count") or 0
    if base_cost and cand_cost and base_samples and cand_samples:
        # Per-execution, not total: a candidate serving more traffic than the
        # baseline would otherwise look expensive purely for being busier.
        base_unit = float(base_cost) / float(base_samples)
        cand_unit = float(cand_cost) / float(cand_samples)
        limit = base_unit * thresholds["cost_regression_multiplier"]
        if base_unit > 0 and cand_unit >= limit:
            found.append(f"cost/execution {cand_unit:.6f} >= {limit:.6f} "
                         f"({thresholds['cost_regression_multiplier']}x baseline)")

    return found


# --------------------------------------------------------------------------- #
# Policy configuration
# --------------------------------------------------------------------------- #
class RollbackPolicyService:
    """CRUD plus most-specific-wins resolution for trigger policies."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def resolve(self, organization_id: uuid.UUID, *, environment_id: uuid.UUID | None,
                agent_id: uuid.UUID | None) -> RollbackTriggerPolicy | None:
        """Most specific enabled policy wins: (environment, agent) beats
        (environment) beats the organization default.

        Returning ``None`` is a real answer and the safe default: **absent a
        policy, no automatic rollback ever fires.** Automation on this platform
        is opt-in, so a tenant that has configured nothing keeps exactly the
        manual behaviour Phases 3.5 and 3.6 gave them, and an organization
        cannot acquire automation by accident."""
        rows = list(self.db.execute(
            select(RollbackTriggerPolicy).where(
                RollbackTriggerPolicy.organization_id == organization_id,
                RollbackTriggerPolicy.enabled.is_(True),
            )
        ).scalars())
        if not rows:
            return None

        def specificity(row: RollbackTriggerPolicy) -> int:
            score = 0
            if row.environment_id is not None:
                score += 2
            if row.agent_id is not None:
                score += 1
            return score

        applicable = [
            row for row in rows
            if (row.environment_id is None or row.environment_id == environment_id)
            and (row.agent_id is None or row.agent_id == agent_id)
        ]
        if not applicable:
            return None
        applicable.sort(key=specificity, reverse=True)
        return applicable[0]

    def list_for_org(self, actor: User) -> list[RollbackTriggerPolicy]:
        return list(self.db.execute(
            select(RollbackTriggerPolicy)
            .where(RollbackTriggerPolicy.organization_id == actor.organization_id)
            .order_by(RollbackTriggerPolicy.created_at.desc())
        ).scalars())

    def upsert(self, actor: User, *, environment_id: uuid.UUID | None,
               agent_id: uuid.UUID | None, thresholds: dict | None = None,
               mode: str = "AUTO_EXECUTE", min_samples: int = DEFAULT_MIN_SAMPLES,
               cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
               enabled: bool = True) -> RollbackTriggerPolicy:
        if mode not in POLICY_MODES:
            raise IdentityError(ErrorCode.VALIDATION_ERROR,
                               f"mode must be one of {sorted(POLICY_MODES)}.")
        if min_samples < 1:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "min_samples must be at least 1.")
        if cooldown_seconds < 0:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, "cooldown_seconds cannot be negative.")
        self._assert_scope_in_tenant(actor, environment_id, agent_id)

        existing = self.db.execute(select(RollbackTriggerPolicy).where(
            RollbackTriggerPolicy.organization_id == actor.organization_id,
            RollbackTriggerPolicy.environment_id.is_(None) if environment_id is None
            else RollbackTriggerPolicy.environment_id == environment_id,
            RollbackTriggerPolicy.agent_id.is_(None) if agent_id is None
            else RollbackTriggerPolicy.agent_id == agent_id,
        )).scalars().first()

        row = existing or RollbackTriggerPolicy(
            organization_id=actor.organization_id,
            environment_id=environment_id,
            agent_id=agent_id,
            created_by=actor.id,
        )
        row.thresholds = dict(thresholds or {})
        row.mode = mode
        row.min_samples = min_samples
        row.cooldown_seconds = cooldown_seconds
        row.enabled = enabled
        if existing is None:
            self.db.add(row)

        _record_event(self.db, AuthorizationAuditEvent.ROLLBACK_POLICY_UPDATED, actor,
                     organization_id=actor.organization_id, agent_id=agent_id, severity="INFO",
                     meta={"environment_id": str(environment_id) if environment_id else None,
                           "mode": mode, "enabled": enabled, "min_samples": min_samples,
                           "cooldown_seconds": cooldown_seconds,
                           "thresholds": row.thresholds})
        self.db.commit()
        self.db.refresh(row)
        return row

    def _assert_scope_in_tenant(self, actor: User, environment_id: uuid.UUID | None,
                               agent_id: uuid.UUID | None) -> None:
        """A policy may only be written for this caller's own environments and
        agents. Without this a tenant could arm automation against another
        tenant's agent by id."""
        if environment_id is not None:
            environment = EnvironmentService(self.db).get_or_404(actor, environment_id)
            if environment.organization_id != actor.organization_id:
                raise IdentityError(ErrorCode.ENVIRONMENT_NOT_FOUND, "Environment not found.")
        if agent_id is not None:
            agent = self.db.get(Agent, agent_id)
            if agent is None or agent.organization_id != actor.organization_id:
                raise IdentityError(ErrorCode.AGENT_NOT_FOUND, "Agent not found.")


# --------------------------------------------------------------------------- #
# The unified rollback
# --------------------------------------------------------------------------- #
class RollbackService:
    """The single implementation every rollback trigger funnels through."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Scope + lookup
    # ------------------------------------------------------------------ #
    def get_or_404(self, actor: User, deployment_id: uuid.UUID) -> AgentDeployment:
        deployment = self.db.get(AgentDeployment, deployment_id)
        if deployment is None or deployment.organization_id != actor.organization_id:
            raise IdentityError(ErrorCode.DEPLOYMENT_NOT_FOUND, "Deployment not found.")
        return deployment

    def active_rollout(self, deployment: AgentDeployment) -> RolloutPlan | None:
        """The rollout, if any, currently promoting this deployment's version."""
        if deployment.environment_id is None:
            return None
        return self.db.execute(
            select(RolloutPlan).where(
                RolloutPlan.organization_id == deployment.organization_id,
                RolloutPlan.agent_id == deployment.agent_id,
                RolloutPlan.environment_id == deployment.environment_id,
                RolloutPlan.candidate_version_id == deployment.agent_version_id,
                RolloutPlan.state.in_(("PENDING", "IN_PROGRESS", "PAUSED")),
            ).order_by(RolloutPlan.created_at.desc())
        ).scalars().first()

    # ------------------------------------------------------------------ #
    # M3-3.7-FR-001/FR-002 -- the authoritative target
    # ------------------------------------------------------------------ #
    def designate_target(self, actor: User, version: AgentVersion,
                         target_version_id: uuid.UUID) -> AgentVersion:
        """Record the last-known-good as this version's rollback target.

        Written through ``VersionLineageService.set_rollback_target`` -- which
        validates same-agent and rollback-eligible status -- rather than by a
        raw column assignment, so this phase inherits the lineage rules
        instead of restating them. That is also why making the field
        authoritative does not break its existing writers: there is still
        exactly one way it gets set."""
        if version.rollback_target_id == target_version_id:
            return version
        return VersionLineageService(self.db).set_rollback_target(version, target_version_id)

    def resolve_target(self, deployment: AgentDeployment, *,
                       plan: RolloutPlan | None = None) -> AgentVersion:
        """The authoritative answer to "where does this rollback go".

        ``rollback_target_id`` on the *currently deployed* version is the
        answer. When a rollout is in scope its ``stable_version_id`` must
        agree with it, and a disagreement **fails closed** rather than picking
        a winner: two sources naming different versions means the platform
        does not actually know what the last-known-good is, and rolling back to
        a guess is worse than refusing, because a wrong rollback looks like a
        successful one.

        Fail-closed is also the answer when there is no target at all
        (M3-3.7-FR-001 / AC-10). Rolling back to nothing is not a rollback."""
        version = self.db.get(AgentVersion, deployment.agent_version_id)
        target_id = version.rollback_target_id if version is not None else None

        if plan is not None and plan.stable_version_id is not None:
            if target_id is None:
                target_id = plan.stable_version_id
            elif target_id != plan.stable_version_id:
                raise IdentityError(
                    ErrorCode.ROLLBACK_TARGET_UNAVAILABLE,
                    "This deployment's designated rollback target and its rollout's stable "
                    "version disagree, so the last-known-good version is ambiguous. Resolve "
                    "the designation before rolling back.")

        if target_id is None:
            raise IdentityError(
                ErrorCode.ROLLBACK_TARGET_UNAVAILABLE,
                "No rollback target is designated for the version this deployment is running, "
                "so there is nothing to roll back to.")

        target = self.db.get(AgentVersion, target_id)
        if target is None or target.agent_id != deployment.agent_id:
            raise IdentityError(
                ErrorCode.ROLLBACK_TARGET_UNAVAILABLE,
                "The designated rollback target is missing or belongs to another agent.")
        if target.status not in ("PUBLISHED", "DEPRECATED"):
            raise IdentityError(
                ErrorCode.ROLLBACK_TARGET_UNAVAILABLE,
                f"The designated rollback target is {target.status}; a rollback may only return "
                "to a previously published version.")
        if target.id == deployment.agent_version_id:
            raise IdentityError(
                ErrorCode.ROLLBACK_TARGET_UNAVAILABLE,
                "The designated rollback target is the version already deployed.")
        return target

    # ------------------------------------------------------------------ #
    # §12 -- automation is subordinate to the kill switch; humans are not
    # ------------------------------------------------------------------ #
    def assert_automation_permitted(self, deployment: AgentDeployment) -> None:
        """Raise if a kill switch covers this deployment.

        Called **only** on the automatic path. See this module's docstring for
        why a manual rollback deliberately remains available while killed:
        automation must never undo a human's kill, but a human must never be
        trapped on the version they are trying to leave."""
        agent = self.db.get(Agent, deployment.agent_id)
        if agent is None or agent.lifecycle_status == "SUSPENDED":
            raise IdentityError(
                ErrorCode.ROLLBACK_BLOCKED_BY_KILL_SWITCH,
                "Automatic rollback is halted: this agent is suspended (kill switch or "
                "lifecycle suspension). Automation never reactivates or rolls past a kill; "
                "clear it explicitly, or roll back manually.")
        if not is_servable(deployment):
            raise IdentityError(
                ErrorCode.ROLLBACK_BLOCKED_BY_KILL_SWITCH,
                "Automatic rollback is halted: this deployment is suspended or is otherwise "
                "not serving. Automation never reactivates a deployment a human stopped.")

    # ------------------------------------------------------------------ #
    # M3-3.7-FR-010 -- the one rollback
    # ------------------------------------------------------------------ #
    def execute(self, actor: User, deployment: AgentDeployment, *, trigger: str,
                reason: str | None = None, justification: str | None = None,
                policy: RollbackTriggerPolicy | None = None,
                evidence: dict | None = None, dedup_key: str | None = None,
                idempotency_key: str | None = None) -> dict:
        """Roll this deployment back to its authoritative target.

        Every trigger lands here. The differences between them are narrow and
        explicit -- who may call it, whether the kill switch blocks it, and
        what gets recorded -- rather than four code paths that drift apart.

        When a rollout is in scope the traffic move is delegated to Phase
        3.5's own ``request_rollback`` rather than reimplemented: that method
        already moves the candidate to zero through 3.4's allocation and
        transitions the plan's state machine, and duplicating either here
        would create the second implementation this phase exists to avoid.
        Outside a rollout the move goes directly through 3.4."""
        if trigger not in TRIGGERS:
            raise IdentityError(ErrorCode.VALIDATION_ERROR, f"Unknown rollback trigger {trigger}.")

        def _do() -> dict:
            return self._execute_inner(
                actor, deployment, trigger=trigger, reason=reason,
                justification=justification, policy=policy, evidence=evidence,
                dedup_key=dedup_key)

        result, _replayed = IdempotencyService(self.db).execute(
            organization_id=actor.organization_id, operation="deployment.rollback",
            key=idempotency_key, payload={"deployment_id": str(deployment.id)}, fn=_do,
        )
        return result

    def _execute_inner(self, actor: User, deployment: AgentDeployment, *, trigger: str,
                       reason: str | None, justification: str | None,
                       policy: RollbackTriggerPolicy | None, evidence: dict | None,
                       dedup_key: str | None) -> dict:
        if trigger == "AUTOMATIC":
            self.assert_automation_permitted(deployment)

        plan = self.active_rollout(deployment)
        target = self.resolve_target(deployment, plan=plan)
        from_version_id = deployment.agent_version_id

        # --- durable intent, committed BEFORE anything moves (FR-050) ------
        event = RollbackEvent(
            organization_id=deployment.organization_id,
            deployment_id=deployment.id,
            agent_id=deployment.agent_id,
            environment_id=deployment.environment_id,
            rollout_plan_id=plan.id if plan is not None else None,
            from_version_id=from_version_id,
            to_version_id=target.id,
            trigger=trigger,
            status="IN_PROGRESS",
            reason=reason,
            justification=justification,
            evidence_ref=evidence or {},
            policy_id=policy.id if policy is not None else None,
            initiated_by=None if trigger == "AUTOMATIC" else actor.id,
            dedup_key=dedup_key,
        )
        self.db.add(event)
        try:
            _record_event(self.db, AuthorizationAuditEvent.DEPLOYMENT_ROLLBACK_STARTED, actor,
                         organization_id=deployment.organization_id,
                         agent_id=deployment.agent_id, deployment_id=deployment.id,
                         severity="WARNING",
                         meta={"trigger": trigger, "from_version_id": str(from_version_id),
                               "to_version_id": str(target.id), "reason": reason,
                               "rollout_plan_id": str(plan.id) if plan is not None else None})
            self.db.commit()
        except IntegrityError:
            # The dedup index fired: another evaluation already claimed this
            # exact threshold crossing. Losing that race is a success, not an
            # error -- the rollback the caller wanted is happening.
            self.db.rollback()
            raise IdentityError(
                ErrorCode.ROLLBACK_CONFLICT,
                "A rollback for this crossing is already in progress.") from None
        except StaleDataError:
            self.db.rollback()
            raise IdentityError(
                ErrorCode.ROLLBACK_CONFLICT,
                "This deployment was modified by another request; reload and retry.") from None

        # --- the traffic move ------------------------------------------------
        self._apply(actor, deployment, target, plan=plan, trigger=trigger, reason=reason)

        return self._complete(actor, event, deployment, target, trigger=trigger)

    def _apply(self, actor: User, deployment: AgentDeployment, target: AgentVersion, *,
               plan: RolloutPlan | None, trigger: str, reason: str | None) -> None:
        """Move traffic to the target -- always through Phase 3.4."""
        note = reason or f"Rollback ({trigger}) to {target.version}."
        if plan is not None:
            # Reuse 3.5's operation wholesale. It moves the candidate to zero
            # and stable to the remainder through 3.4's ``set_weights`` and
            # drives the plan's own state machine; this phase adds the policy
            # that decided to call it, not a second way of doing it.
            CanaryRolloutService(self.db).request_rollback(actor, plan, reason=note)
            return

        agent = self.db.get(Agent, deployment.agent_id)
        environment = self._environment_for(deployment)
        if environment is None:
            raise IdentityError(
                ErrorCode.ROLLBACK_TARGET_UNAVAILABLE,
                "This deployment has no governed environment, so its traffic allocation "
                "cannot be addressed.")
        entries = [
            {"agent_version_id": target.id, "weight": 100},
            {"agent_version_id": deployment.agent_version_id, "weight": 0},
        ]
        try:
            TrafficAllocationService(self.db).set_weights(
                actor, agent, environment, entries, reason=note)
        except IdentityError as exc:
            if exc.code == ErrorCode.TRAFFIC_ALLOCATION_CONFLICT:
                raise IdentityError(
                    ErrorCode.ROLLBACK_CONFLICT,
                    f"This agent's traffic allocation changed during the rollback: {exc.message}",
                ) from None
            raise

    def _environment_for(self, deployment: AgentDeployment) -> Environment | None:
        if deployment.environment_id is None:
            return None
        return self.db.get(Environment, deployment.environment_id)

    def _complete(self, actor: User, event: RollbackEvent, deployment: AgentDeployment,
                  target: AgentVersion, *, trigger: str) -> dict:
        event.status = "COMPLETED"
        event.completed_at = _now()
        _record_event(self.db, AuthorizationAuditEvent.RUNTIME_ROLLBACK_COMPLETED, actor,
                     organization_id=deployment.organization_id, agent_id=deployment.agent_id,
                     deployment_id=deployment.id, severity="WARNING",
                     meta={"trigger": trigger, "to_version_id": str(target.id),
                           "to_version": target.version,
                           "rollback_event_id": str(event.id)})
        self.db.commit()
        self.db.refresh(event)
        return self.read_model(event)

    # ------------------------------------------------------------------ #
    # §11 -- forced rollback
    # ------------------------------------------------------------------ #
    def force(self, actor: User, deployment: AgentDeployment, *, justification: str,
              target_version_id: uuid.UUID | None = None,
              idempotency_key: str | None = None) -> dict:
        """A dangerous operation, and treated as one.

        The override it grants is narrow and specific: a forced rollback may
        name a target explicitly, bypassing the designated-target requirement
        that makes an ordinary rollback fail closed. That is the whole point --
        it is the escape hatch for the case where the designation itself is
        what is wrong, at 3am, with production down.

        It does **not** override the kill switch, and deliberately so. Nothing
        in this module can, because a kill switch is the one control whose
        value comes entirely from being unconditional."""
        if not justification or not justification.strip():
            raise IdentityError(
                ErrorCode.ROLLBACK_FORCE_UNAUTHORIZED,
                "A forced rollback requires a written justification; it is recorded as a "
                "dangerous operation.")

        if target_version_id is not None:
            target = self.db.get(AgentVersion, target_version_id)
            if target is None or target.agent_id != deployment.agent_id:
                raise IdentityError(ErrorCode.ROLLBACK_TARGET_UNAVAILABLE,
                                   "Target version not found for this agent.")
            if target.status not in ("PUBLISHED", "DEPRECATED"):
                raise IdentityError(
                    ErrorCode.ROLLBACK_TARGET_UNAVAILABLE,
                    f"The named target is {target.status}; even a forced rollback may only "
                    "return to a previously published version.")
            version = self.db.get(AgentVersion, deployment.agent_version_id)
            if version is not None:
                self.designate_target(actor, version, target.id)

        _record_event(self.db, AuthorizationAuditEvent.ROLLBACK_FORCED, actor,
                     organization_id=deployment.organization_id, agent_id=deployment.agent_id,
                     deployment_id=deployment.id, severity="CRITICAL",
                     meta={"justification": justification,
                           "target_version_id": str(target_version_id) if target_version_id
                           else None})
        self.db.commit()

        return self.execute(actor, deployment, trigger="FORCED",
                            reason="Forced rollback.", justification=justification,
                            idempotency_key=idempotency_key)

    # ------------------------------------------------------------------ #
    # M3-3.7-FR-020..024 -- bounded, idempotent trigger evaluation
    # ------------------------------------------------------------------ #
    def evaluate(self, actor: User, deployment: AgentDeployment, *,
                 idempotency_key: str | None = None) -> dict:
        """Evaluate this deployment's trigger policy once and act if warranted.

        **Bounded and interim, exactly as 3.5's auto-advance is.** One call
        evaluates one deployment and performs at most one rollback. It is not
        a scheduler and does not loop; Phase 3.8 will call this exact method on
        a timer with no change required here -- the same relationship
        ``app/integration/scheduler.py`` already documents for its own eventual
        replacement."""
        def _do() -> dict:
            return self._evaluate_inner(actor, deployment)

        result, _replayed = IdempotencyService(self.db).execute(
            organization_id=actor.organization_id, operation="deployment.rollback.evaluate",
            key=idempotency_key, payload={"deployment_id": str(deployment.id)}, fn=_do,
        )
        return result

    def _evaluate_inner(self, actor: User, deployment: AgentDeployment) -> dict:
        # Recovery first (FR-050): an intent formed but never finished is
        # completed before any new judgement is made, so a crashed rollback is
        # never left behind by the next tick.
        resumed = self.resume_incomplete(actor, deployment)
        if resumed is not None:
            return {"action": "RESUMED", "rollback": resumed,
                    "decision": TriggerDecision(False, "UNKNOWN", (),
                                                withheld_reason="Resumed an interrupted "
                                                                "rollback.").as_dict()}

        policy = RollbackPolicyService(self.db).resolve(
            deployment.organization_id, environment_id=deployment.environment_id,
            agent_id=deployment.agent_id)
        if policy is None:
            return {"action": "NO_POLICY", "rollback": None,
                    "decision": TriggerDecision(
                        False, "UNKNOWN", (),
                        withheld_reason="No enabled rollback trigger policy applies; automatic "
                                        "rollback is opt-in.").as_dict()}

        # §12 is checked *before* health, not after, and the ordering is
        # load-bearing. The health engine independently returns UNKNOWN for a
        # vetoed candidate, so a kill switch would otherwise surface as
        # "health verdict UNKNOWN is not evidence of a regression" -- safe, but
        # the wrong explanation. An operator needs to see that automation stood
        # down because it was *told to*, not because it could not form a
        # judgement. Checking first also spares a killed agent a pointless
        # aggregation over its execution history.
        try:
            self.assert_automation_permitted(deployment)
        except IdentityError as exc:
            # Reported rather than raised, so a future scheduler sweeping many
            # deployments is not aborted by one killed agent -- it simply does
            # not act on that one. The same choice 3.5 made on its own
            # automated path.
            return {"action": "WITHHELD", "rollback": None,
                    "decision": TriggerDecision(False, "UNKNOWN", (),
                                                withheld_reason=exc.message).as_dict()}

        # Anti-flap, second guard: only a version actually *on trial* is a
        # candidate for automatic rollback. A version holding zero traffic has
        # already been rolled away from (or never rolled to), so re-judging it
        # could only produce a rollback of something that is not serving --
        # which is how a policy that cannot settle starts thrashing. This is
        # also what keeps the restored last-known-good from being rolled back
        # by the same policy on the next tick.
        if not self._is_on_trial(deployment):
            return {"action": "NO_ACTION", "rollback": None,
                    "decision": TriggerDecision(
                        False, "UNKNOWN", (),
                        withheld_reason="This version holds no traffic, so it is not on trial; "
                                        "automatic rollback applies only to a serving "
                                        "candidate.").as_dict()}

        verdict = self._health_for(deployment, policy)
        thresholds = thresholds_for_policy(policy)
        decision = evaluate_thresholds(
            verdict.state, verdict.metrics.as_dict(), verdict.baseline, thresholds,
            min_samples=policy.min_samples)

        if not decision.should_rollback:
            return {"action": "NO_ACTION", "rollback": None, "decision": decision.as_dict()}

        # A crossing was detected. Everything below decides whether to act on
        # it, and records the reason when it declines.
        withheld = self._withholding_reason(deployment, policy)
        if withheld is not None:
            held = TriggerDecision(False, decision.health_state, decision.reasons,
                                   withheld_reason=withheld)
            return {"action": "WITHHELD", "rollback": None, "decision": held.as_dict()}

        _record_event(self.db, AuthorizationAuditEvent.ROLLBACK_TRIGGER_FIRED, actor,
                     organization_id=deployment.organization_id, agent_id=deployment.agent_id,
                     deployment_id=deployment.id, severity="CRITICAL",
                     meta={"policy_id": str(policy.id), "mode": policy.mode,
                           "health_state": decision.health_state,
                           "reasons": list(decision.reasons),
                           "thresholds": thresholds})
        self.db.commit()

        evidence = {
            "health_state": verdict.state,
            "metrics": verdict.metrics.as_dict(),
            "baseline": verdict.baseline,
            "window_start": verdict.window_start.isoformat(),
            "window_end": verdict.window_end.isoformat(),
            "explanation": verdict.explanation,
            "reasons": list(decision.reasons),
            "policy_id": str(policy.id),
        }
        rollback = self.execute(
            actor, deployment, trigger="AUTOMATIC",
            reason="; ".join(decision.reasons), policy=policy, evidence=evidence,
            dedup_key=self._dedup_key(deployment))
        return {"action": "ROLLED_BACK", "rollback": rollback, "decision": decision.as_dict()}

    def _withholding_reason(self, deployment: AgentDeployment,
                            policy: RollbackTriggerPolicy) -> str | None:
        """Reasons to detect a regression but decline to act on it."""
        if policy.mode == "NOTIFY_ONLY":
            return ("Policy mode is NOTIFY_ONLY: the regression was detected and recorded, "
                    "and traffic was deliberately left unchanged.")
        # §12 is re-checked here as well as before the health evaluation above.
        # The two are not redundant: a kill switch activated *during* the
        # aggregation must still stop the rollback, and this is the last point
        # before ``execute`` at which it can. ``execute`` itself checks a third
        # time, because it is reachable without going through this method.
        try:
            self.assert_automation_permitted(deployment)
        except IdentityError as exc:
            return exc.message
        if self._in_cooldown(deployment, policy):
            return (f"Within the {policy.cooldown_seconds}s anti-flap cooldown of a previous "
                    "automatic rollback for this agent and environment.")
        return None

    def _is_on_trial(self, deployment: AgentDeployment) -> bool:
        """Is this deployment's version currently carrying traffic?

        No allocation at all means the implicit-100% case Phase 3.4 defines --
        the version is serving, so it is on trial. An allocation that exists
        and gives it zero is the case this guard exists for."""
        if deployment.environment_id is None:
            return True
        allocation = TrafficAllocationService(self.db).current(
            deployment.organization_id, deployment.agent_id, deployment.environment_id)
        if allocation is None:
            return True
        weights = TrafficAllocationService(self.db).weights_for(allocation.id)
        for weight in weights:
            if weight.agent_version_id == deployment.agent_version_id:
                return weight.weight > 0
        return False

    def _in_cooldown(self, deployment: AgentDeployment,
                     policy: RollbackTriggerPolicy) -> bool:
        if policy.cooldown_seconds <= 0:
            return False
        cutoff = _now() - timedelta(seconds=policy.cooldown_seconds)
        recent = self.db.execute(
            select(RollbackEvent).where(
                RollbackEvent.agent_id == deployment.agent_id,
                RollbackEvent.environment_id == deployment.environment_id,
                RollbackEvent.trigger == "AUTOMATIC",
                RollbackEvent.created_at >= cutoff,
            ).limit(1)
        ).scalars().first()
        return recent is not None

    def _dedup_key(self, deployment: AgentDeployment) -> str:
        """One automatic rollback per (deployment, deployed version).

        Keyed on the version rather than on a timestamp or a crossing id: the
        crossing is only meaningful because *this* version is serving, and once
        it stops serving the crossing is moot. This also makes the guard
        naturally correct across restarts, since it is derived from state
        rather than remembered."""
        return f"auto:{deployment.id}:{deployment.agent_version_id}"

    def _health_for(self, deployment: AgentDeployment, policy: RollbackTriggerPolicy):
        """Phase 3.5's engine, consulted -- never a second health computation.

        ``require_servable`` is deliberately left at its default here. The
        automatic path has already run its own §12 check, and asking the health
        engine to veto again would collapse "this candidate is unhealthy" and
        "this candidate is killed" into one answer, when the trigger logic
        needs to tell them apart."""
        window_end = _now()
        window_start = window_end - timedelta(seconds=DEFAULT_WINDOW_SECONDS)
        agent = self.db.get(Agent, deployment.agent_id)
        environment = self._environment_for(deployment)
        version = self.db.get(AgentVersion, deployment.agent_version_id)
        baseline_id = version.rollback_target_id if version is not None else None
        return HealthEvaluationService(self.db).evaluate(
            organization_id=deployment.organization_id,
            agent=agent,
            agent_version_id=deployment.agent_version_id,
            window_start=window_start,
            window_end=window_end,
            min_samples=policy.min_samples,
            environment=environment,
            baseline_version_id=baseline_id,
            deployment=deployment,
        )

    # ------------------------------------------------------------------ #
    # M3-3.7-FR-050 -- recovery
    # ------------------------------------------------------------------ #
    def resume_incomplete(self, actor: User, deployment: AgentDeployment) -> dict | None:
        """Finish a rollback whose intent was recorded but whose traffic move
        never completed.

        Safe to call repeatedly and safe to call on a healthy system, where it
        finds nothing. Re-applying the move is harmless because 3.4's
        allocation is a declaration of the desired end state rather than a
        delta -- setting the same weights twice leaves the same allocation, so
        there is no half-applied state that a resume could compound."""
        pending = self.db.execute(
            select(RollbackEvent).where(
                RollbackEvent.deployment_id == deployment.id,
                RollbackEvent.status == "IN_PROGRESS",
            ).order_by(RollbackEvent.created_at.asc()).limit(1)
        ).scalars().first()
        if pending is None:
            return None

        target = self.db.get(AgentVersion, pending.to_version_id)
        if target is None:
            pending.status = "FAILED"
            pending.completed_at = _now()
            self.db.commit()
            return self.read_model(pending)

        plan = self.db.get(RolloutPlan, pending.rollout_plan_id) if pending.rollout_plan_id \
            else None
        # A rollout already driven to ROLLBACK_REQUESTED by the interrupted
        # attempt must not be pushed through its state machine twice.
        replayable_plan = plan if plan is not None and plan.state in (
            "PENDING", "IN_PROGRESS", "PAUSED") else None
        self._apply(actor, deployment, target, plan=replayable_plan,
                    trigger=pending.trigger, reason="Resuming an interrupted rollback.")
        return self._complete(actor, pending, deployment, target, trigger=pending.trigger)

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def history(self, actor: User, deployment_id: uuid.UUID, *,
                limit: int = 50, offset: int = 0) -> list[RollbackEvent]:
        return list(self.db.execute(
            select(RollbackEvent)
            .where(RollbackEvent.organization_id == actor.organization_id,
                   RollbackEvent.deployment_id == deployment_id)
            .order_by(RollbackEvent.created_at.desc())
            .limit(limit).offset(offset)
        ).scalars())

    def read_model(self, event: RollbackEvent) -> dict:
        from app.runtime.schemas import RollbackEventRead  # leaf module
        return RollbackEventRead.model_validate(event).model_dump(mode="json")
