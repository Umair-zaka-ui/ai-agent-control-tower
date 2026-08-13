"""ACT-SRS-M3 §Phase-3.5 §6/§7 (M3-3.5-FR-020..024, FR-030..031) -- the
AI-aware release-health engine (ruling #3).

**What makes this "AI-aware" rather than a ping.** The pre-existing
``deployment_health`` table (§49/§50, untouched here per ruling #3) records a
liveness heartbeat: a worker reported in, the process is up. That is a fine
answer to "is it running" and a useless answer to "should this version get more
traffic". A model version can be perfectly *alive* while refusing every third
request, timing out on long prompts, tripping policy denials, or quietly costing
four times as much per call. So this engine ignores heartbeats entirely and
aggregates what actually happened -- ``agent_executions`` rows -- over a window.

**The signals this repository actually has**, confirmed by reading the model
(``app.models.runtime.AgentExecution``) rather than assumed from the SRS's
wish-list:

===========================  ==========================================
Signal                        Source
===========================  ==========================================
success / failure / timeout   ``status`` (SUCCEEDED / FAILED,
                              DEAD_LETTERED / TIMED_OUT)
policy denials                ``status`` (DENIED, BLOCKED) -- the
                              runtime-policy and authorization outcomes
latency                       ``duration_ms`` (mean and p95)
cost                          ``cost_amount``
tokens                        ``total_tokens``
provider / tool failure class ``error_code`` (the 5.7a.4 taxonomy)
===========================  ==========================================

External-system integration failure counts are *not* separately available on
an execution row -- the same missing runtime-to-integration dependency link
Phases 3.2 and 3.3 already reported as a gap (this layer has no way to know
which external system a version even depends on, and the runtime-never-knows
boundary keeps that vocabulary out of this package entirely). Reported again
here rather than built around; provider and tool failures are captured through
``error_code`` instead.

**INSUFFICIENT_DATA is first-class** (M3-3.5-FR-022). A 5% canary with two
successful calls has proven nothing, and the single most dangerous bug this
engine could have is reporting that as HEALTHY -- "no failures observed" is not
"no failures happen". Below the stage's minimum sample count the verdict is
INSUFFICIENT_DATA regardless of how good the few samples look, and
``rollout.health_requirement_satisfied`` refuses to let it clear any gate.

**A veto is never healthy** (M3-3.5-FR-024, §12). If the agent is suspended or
killed, or the candidate's deployment is not servable under Phase 3.4's
union-with-veto predicate, this engine returns UNKNOWN -- never HEALTHY. That
matters because automation reads this verdict: a health engine that concluded
"healthy, advance" for a killed agent would let automation walk straight past
the kill switch."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Float, case, func, select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.runtime import (
    AgentDeployment,
    AgentExecution,
    DeploymentHealthEvaluation,
    Environment,
    RolloutPlan,
)
from app.runtime.deployment.traffic import is_servable, servable_clause

# Execution statuses that count as an observed outcome for health purposes.
# An execution still queued or running has not produced a verdict yet and must
# not dilute the rates -- counting it as "not a failure" would make a stalled
# canary look healthier the more stuck it got.
TERMINAL_FOR_HEALTH: frozenset[str] = frozenset({
    "SUCCEEDED", "FAILED", "TIMED_OUT", "DEAD_LETTERED", "DENIED", "BLOCKED", "CANCELLED",
})
FAILURE_STATUSES: frozenset[str] = frozenset({"FAILED", "DEAD_LETTERED"})
TIMEOUT_STATUSES: frozenset[str] = frozenset({"TIMED_OUT"})
DENIAL_STATUSES: frozenset[str] = frozenset({"DENIED", "BLOCKED"})

# Platform defaults. Overridable per environment via
# ``Environment.policy["canary_health_thresholds"]`` -- the same
# policy-carries-the-override pattern Phase 3.3 established for
# ``preflight_severity_overrides`` / ``preflight_freshness_bound_seconds``,
# rather than a second configuration mechanism.
DEFAULT_THRESHOLDS: dict[str, float] = {
    # Fraction of terminal executions that failed or timed out.
    "degraded_error_rate": 0.05,
    "unhealthy_error_rate": 0.20,
    # Policy denials are a separate signal from failures: a version that is
    # being denied is not erroring, it is being refused, and that is still a
    # reason not to give it more traffic.
    "degraded_denial_rate": 0.10,
    "unhealthy_denial_rate": 0.30,
    # Baseline comparison (§7): how much worse than stable the candidate's
    # error rate may be, in absolute percentage points, before the gap alone
    # is treated as a candidate regression.
    #
    # Deliberately *narrower* than ``degraded_error_rate``. If the margin were
    # as wide as the absolute threshold, the baseline rule could never fire on
    # its own -- any gap big enough to breach it would already have tripped the
    # absolute check -- and §7's whole point is catching a candidate that is
    # measurably worse than the version it would replace while still looking
    # acceptable in isolation.
    "baseline_error_rate_margin": 0.02,
}


def thresholds_for(environment: Environment | None) -> dict[str, float]:
    resolved = dict(DEFAULT_THRESHOLDS)
    if environment is not None:
        overrides = (environment.policy or {}).get("canary_health_thresholds") or {}
        for key, value in overrides.items():
            if key in resolved and isinstance(value, (int, float)) and not isinstance(value, bool):
                resolved[key] = float(value)
    return resolved


@dataclass(frozen=True, slots=True)
class HealthMetrics:
    """The aggregate for one version over one window -- a plain value, so it
    can be compared against a baseline and serialized into the evaluation row
    without dragging a Session along."""

    sample_count: int = 0
    succeeded: int = 0
    failed: int = 0
    timed_out: int = 0
    denied: int = 0
    error_rate: float = 0.0
    denial_rate: float = 0.0
    avg_duration_ms: float | None = None
    p95_duration_ms: float | None = None
    total_cost: float = 0.0
    total_tokens: int = 0
    error_codes: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "sample_count": self.sample_count,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "timed_out": self.timed_out,
            "denied": self.denied,
            "error_rate": round(self.error_rate, 6),
            "denial_rate": round(self.denial_rate, 6),
            "avg_duration_ms": self.avg_duration_ms,
            "p95_duration_ms": self.p95_duration_ms,
            "total_cost": round(self.total_cost, 8),
            "total_tokens": self.total_tokens,
            "error_codes": self.error_codes,
        }


@dataclass(frozen=True, slots=True)
class HealthVerdict:
    state: str
    metrics: HealthMetrics
    baseline: dict | None
    window_start: datetime
    window_end: datetime
    explanation: str


class HealthEvaluationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Aggregation (AC-04, AC-14)
    # ------------------------------------------------------------------ #
    def _aggregate(self, organization_id: uuid.UUID, agent_version_id: uuid.UUID,
                  window_start: datetime, window_end: datetime) -> HealthMetrics:
        """One indexed pass over ``agent_executions`` (AC-14).

        Uses the composite index ``ix_agent_executions_version_created`` on
        ``(agent_version_id, created_at)`` added by migration 0041 -- before
        that index this table had nothing covering a per-version time window
        (``agent_version_id`` alone, and no index touching ``created_at``), so
        a canary evaluating health every few seconds would have scanned the
        whole execution history of the platform.

        Tenant-scoped by ``organization_id`` in the same predicate, never by
        filtering afterwards: health aggregation must not be able to see
        another tenant's executions even for a version id that somehow
        collided."""
        counted = case((AgentExecution.status.in_(tuple(TERMINAL_FOR_HEALTH)), 1), else_=0)
        row = self.db.execute(
            select(
                func.coalesce(func.sum(counted), 0),
                func.coalesce(func.sum(case((AgentExecution.status == "SUCCEEDED", 1), else_=0)), 0),
                func.coalesce(func.sum(case((AgentExecution.status.in_(tuple(FAILURE_STATUSES)), 1), else_=0)), 0),
                func.coalesce(func.sum(case((AgentExecution.status.in_(tuple(TIMEOUT_STATUSES)), 1), else_=0)), 0),
                func.coalesce(func.sum(case((AgentExecution.status.in_(tuple(DENIAL_STATUSES)), 1), else_=0)), 0),
                func.avg(AgentExecution.duration_ms),
                func.percentile_cont(0.95).within_group(
                    AgentExecution.duration_ms.cast(Float).asc()),
                func.coalesce(func.sum(AgentExecution.cost_amount), 0),
                func.coalesce(func.sum(AgentExecution.total_tokens), 0),
            ).where(
                AgentExecution.organization_id == organization_id,
                AgentExecution.agent_version_id == agent_version_id,
                AgentExecution.created_at >= window_start,
                AgentExecution.created_at <= window_end,
            )
        ).one()

        sample_count = int(row[0] or 0)
        succeeded, failed, timed_out, denied = (int(row[i] or 0) for i in (1, 2, 3, 4))
        avg_duration = float(row[5]) if row[5] is not None else None
        p95_duration = float(row[6]) if row[6] is not None else None

        error_codes: dict[str, int] = {}
        if sample_count:
            for code, count in self.db.execute(
                select(AgentExecution.error_code, func.count())
                .where(
                    AgentExecution.organization_id == organization_id,
                    AgentExecution.agent_version_id == agent_version_id,
                    AgentExecution.created_at >= window_start,
                    AgentExecution.created_at <= window_end,
                    AgentExecution.error_code.is_not(None),
                )
                .group_by(AgentExecution.error_code)
            ):
                error_codes[code] = int(count)

        divisor = sample_count or 1
        return HealthMetrics(
            sample_count=sample_count, succeeded=succeeded, failed=failed,
            timed_out=timed_out, denied=denied,
            error_rate=(failed + timed_out) / divisor if sample_count else 0.0,
            denial_rate=denied / divisor if sample_count else 0.0,
            avg_duration_ms=avg_duration, p95_duration_ms=p95_duration,
            total_cost=float(row[7] or 0), total_tokens=int(row[8] or 0),
            error_codes=error_codes,
        )

    # ------------------------------------------------------------------ #
    # Classification (AC-05, AC-06, AC-07)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _classify(metrics: HealthMetrics, thresholds: dict[str, float]) -> tuple[str, str]:
        if metrics.error_rate >= thresholds["unhealthy_error_rate"]:
            return "UNHEALTHY", (
                f"Error rate {metrics.error_rate:.1%} is at or above the unhealthy "
                f"threshold {thresholds['unhealthy_error_rate']:.1%}."
            )
        if metrics.denial_rate >= thresholds["unhealthy_denial_rate"]:
            return "UNHEALTHY", (
                f"Policy-denial rate {metrics.denial_rate:.1%} is at or above the unhealthy "
                f"threshold {thresholds['unhealthy_denial_rate']:.1%}."
            )
        if metrics.error_rate >= thresholds["degraded_error_rate"]:
            return "DEGRADED", (
                f"Error rate {metrics.error_rate:.1%} is at or above the degraded "
                f"threshold {thresholds['degraded_error_rate']:.1%}."
            )
        if metrics.denial_rate >= thresholds["degraded_denial_rate"]:
            return "DEGRADED", (
                f"Policy-denial rate {metrics.denial_rate:.1%} is at or above the degraded "
                f"threshold {thresholds['degraded_denial_rate']:.1%}."
            )
        return "HEALTHY", (
            f"{metrics.sample_count} executions, error rate {metrics.error_rate:.1%}, "
            f"denial rate {metrics.denial_rate:.1%} -- within all thresholds."
        )

    @staticmethod
    def _apply_baseline(candidate_state: str, explanation: str, candidate: HealthMetrics,
                       stable: HealthMetrics, thresholds: dict[str, float]) -> tuple[str, str, dict]:
        """§7's baseline comparison, and the candidate-vs-provider-wide
        distinction (FR-031) this phase actually implements.

        Two findings, both recorded:

        1. **Regression relative to stable.** If the candidate's error rate
           exceeds the stable version's by more than the configured margin, the
           candidate is worse than what it would replace -- even if its
           absolute rate happens to sit under the degraded threshold. That
           earns a DEGRADED floor, because "better than an arbitrary constant"
           is the wrong bar when a known-good comparator is running right now.

        2. **Likely provider-wide degradation.** If *both* candidate and
           stable are elevated together, the candidate is probably not the
           cause -- an upstream model provider or a shared dependency is.
           Recorded as ``likely_provider_wide``.

        Crucially, finding 2 **softens blame but never restores HEALTHY**. It
        would be an easy and dangerous mistake to let "it's not the
        candidate's fault" mean "so carry on promoting": a provider-wide
        incident is exactly when *no* version should be earning more traffic.
        So the verdict is floored at DEGRADED, which no sensible stage accepts,
        and the incident is named in the explanation instead of silently
        excusing the numbers. Full causal analysis stays deferred (§7)."""
        baseline: dict = {
            "stable_metrics": stable.as_dict(),
            "candidate_error_rate": round(candidate.error_rate, 6),
            "stable_error_rate": round(stable.error_rate, 6),
            "comparable": stable.sample_count > 0,
        }
        if stable.sample_count == 0:
            baseline["note"] = (
                "No stable-version executions in this window; compared against absolute "
                "thresholds only."
            )
            return candidate_state, explanation, baseline

        margin = thresholds["baseline_error_rate_margin"]
        both_elevated = (
            candidate.error_rate >= thresholds["degraded_error_rate"]
            and stable.error_rate >= thresholds["degraded_error_rate"]
        )
        baseline["likely_provider_wide"] = both_elevated
        regressed = candidate.error_rate > stable.error_rate + margin
        baseline["regression_vs_stable"] = regressed and not both_elevated

        if both_elevated:
            return (
                candidate_state if candidate_state in ("UNHEALTHY", "DEGRADED") else "DEGRADED",
                explanation + (
                    f" The stable version is also elevated ({stable.error_rate:.1%}), so this "
                    "looks provider-wide rather than candidate-specific -- the candidate is not "
                    "blamed, but no version is promoted during a shared degradation."
                ),
                baseline,
            )
        if regressed and candidate_state == "HEALTHY":
            return "DEGRADED", (
                f"Candidate error rate {candidate.error_rate:.1%} exceeds the stable version's "
                f"{stable.error_rate:.1%} by more than the {margin:.1%} margin -- a regression "
                "relative to the version it would replace, even though it is within absolute "
                "thresholds."
            ), baseline
        return candidate_state, explanation, baseline

    # ------------------------------------------------------------------ #
    # The public entry point
    # ------------------------------------------------------------------ #
    def evaluate(self, *, organization_id: uuid.UUID, agent: Agent,
                agent_version_id: uuid.UUID, window_start: datetime, window_end: datetime,
                min_samples: int, environment: Environment | None = None,
                baseline_version_id: uuid.UUID | None = None,
                deployment: AgentDeployment | None = None,
                require_servable: bool = False) -> HealthVerdict:
        """Compute a verdict. Order matters and is deliberate:

        1. **Veto first** (FR-024/§12). A killed or non-servable candidate is
           UNKNOWN before a single row is aggregated -- automation must never
           receive "healthy" for something the gate would refuse to serve.
        2. **Sample sufficiency next** (FR-022). Below the minimum, the answer
           is INSUFFICIENT_DATA no matter how clean the few samples look.
        3. Only then are thresholds and the baseline applied."""
        thresholds = thresholds_for(environment)

        veto = self._veto_reason(agent, deployment, require_servable=require_servable)
        if veto is not None:
            return HealthVerdict(
                state="UNKNOWN", metrics=HealthMetrics(), baseline=None,
                window_start=window_start, window_end=window_end,
                explanation=f"Not evaluable: {veto}",
            )

        metrics = self._aggregate(organization_id, agent_version_id, window_start, window_end)

        if metrics.sample_count < max(min_samples, 1):
            return HealthVerdict(
                state="INSUFFICIENT_DATA", metrics=metrics, baseline=None,
                window_start=window_start, window_end=window_end,
                explanation=(
                    f"Only {metrics.sample_count} executions in the window; at least "
                    f"{max(min_samples, 1)} are required before health can be judged. "
                    "A thin sample is not evidence of health."
                ),
            )

        state, explanation = self._classify(metrics, thresholds)
        baseline = None
        if baseline_version_id is not None and baseline_version_id != agent_version_id:
            stable = self._aggregate(organization_id, baseline_version_id, window_start, window_end)
            state, explanation, baseline = self._apply_baseline(
                state, explanation, metrics, stable, thresholds)

        return HealthVerdict(state=state, metrics=metrics, baseline=baseline,
                            window_start=window_start, window_end=window_end,
                            explanation=explanation)

    def _veto_reason(self, agent: Agent, deployment: AgentDeployment | None, *,
                    require_servable: bool = False) -> str | None:
        """The §12 veto, read from the *same* fields Phase 3.4's resolver reads
        -- never a second, parallel notion of "is this thing allowed to run".
        ``KillSwitchService`` suspends the agent (AGENT scope) or the
        deployment's ``status`` (ORGANIZATION/PROJECT/PLATFORM scope), and both
        are covered here.

        ``require_servable`` closes what would otherwise be a real hole. A
        caller that looked up the candidate's servable deployment and found
        **none** -- because it was paused, superseded, retired or suspended --
        is describing a candidate that cannot serve at all. Treating that
        absence as "no veto to apply" would let the engine aggregate the
        version's older executions and cheerfully report HEALTHY for something
        the execution gate is refusing to route to. Rollout callers therefore
        pass ``require_servable=True``; a bare ad-hoc evaluation of some
        version's numbers (no deployment context) does not."""
        if agent.lifecycle_status == "SUSPENDED":
            return "the agent is suspended (kill switch or lifecycle suspension)."
        if agent.lifecycle_status != "ACTIVE":
            return f"the agent is {agent.lifecycle_status}, not ACTIVE."
        if deployment is None:
            if require_servable:
                return (
                    "the candidate has no servable deployment in this environment "
                    "(paused, superseded, retired, or suspended by the kill switch)."
                )
            return None
        if not is_servable(deployment):
            return (
                f"the serving deployment is not servable "
                f"(status={deployment.status}, lifecycle_state={deployment.lifecycle_state})."
            )
        return None

    # ------------------------------------------------------------------ #
    # Persistence (FR-023, AC-08)
    # ------------------------------------------------------------------ #
    def persist(self, verdict: HealthVerdict, *, organization_id: uuid.UUID,
               agent_version_id: uuid.UUID, deployment_id: uuid.UUID | None,
               rollout_plan_id: uuid.UUID | None,
               evaluated_by: uuid.UUID | None) -> DeploymentHealthEvaluation:
        row = DeploymentHealthEvaluation(
            organization_id=organization_id, deployment_id=deployment_id,
            agent_version_id=agent_version_id, rollout_plan_id=rollout_plan_id,
            health_state=verdict.state, sample_count=verdict.metrics.sample_count,
            metrics={**verdict.metrics.as_dict(), "explanation": verdict.explanation},
            baseline_ref=verdict.baseline,
            window_start=verdict.window_start, window_end=verdict.window_end,
            evaluated_by=evaluated_by,
        )
        self.db.add(row)
        return row

    def servable_deployment_for(self, organization_id: uuid.UUID, agent_id: uuid.UUID,
                               environment_id: uuid.UUID,
                               agent_version_id: uuid.UUID) -> AgentDeployment | None:
        """The deployment currently serving this version in this environment,
        under Phase 3.4's own servability predicate -- imported, not restated,
        so the rollout can never disagree with the resolver about what is
        serving."""
        return self.db.execute(
            select(AgentDeployment)
            .where(AgentDeployment.organization_id == organization_id,
                   AgentDeployment.agent_id == agent_id,
                   AgentDeployment.environment_id == environment_id,
                   AgentDeployment.agent_version_id == agent_version_id,
                   servable_clause())
            .order_by(AgentDeployment.deployed_at.desc().nullslast(), AgentDeployment.id)
        ).scalars().first()

    def latest_for_plan(self, rollout_plan_id: uuid.UUID,
                       limit: int = 20) -> list[DeploymentHealthEvaluation]:
        return list(self.db.execute(
            select(DeploymentHealthEvaluation)
            .where(DeploymentHealthEvaluation.rollout_plan_id == rollout_plan_id)
            .order_by(DeploymentHealthEvaluation.evaluated_at.desc())
            .limit(limit)
        ).scalars())


def plan_environment(db: Session, plan: RolloutPlan) -> Environment | None:
    return db.get(Environment, plan.environment_id)
