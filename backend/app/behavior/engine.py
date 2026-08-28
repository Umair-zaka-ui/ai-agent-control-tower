"""``BehavioralEvaluator`` — the aggregation and the evaluation order
(M4-4.5-FR-001..004, FR-020..021, FR-030..031).

**This reuses Phase 3.5's engine shape rather than forking a second one**, and
the reuse is structural, not a resemblance:

1. **Veto first.** A killed or suspended agent is ``UNKNOWN`` before a single
   row is aggregated. Phase 3.5 vetoes because automation reads its verdict to
   move traffic; this vetoes for a sharper reason of its own — *a killed
   agent's runtime data describes the kill, not the agent*. Executions
   cancelled by a kill switch would show as a huge error spike, and reporting
   that as ANOMALOUS would fire an alarm about the intervention rather than
   about the behavior, at exactly the moment an operator is already busy.
2. **Sufficiency next.** Below the minimum sample count the answer is
   ``INSUFFICIENT_DATA`` regardless of how clean or how alarming the few
   samples look. Phase 3.5's line applies verbatim: *a thin sample is not
   evidence*.
3. **Absolute thresholds**, then **baseline comparison** — the same order as
   3.5's ``_classify`` then ``_apply_baseline``.

The baseline differs, and deliberately. Phase 3.5 compares a *candidate version
against the stable version over the same window* — the right comparison when
asking "should this version get more traffic". This compares *an agent against
itself over the preceding window* — the right comparison when asking "has this
agent's behavior changed". Same engine shape, different axis, because they are
different questions.

**A finding is a signal and never enforcement.** Nothing in this package writes
an execution's status, raises a governance exception, or reaches the kill
switch; Phase 4.3's engine remains the only thing on this platform that can
stop an execution. Asserted over the AST, the same proof Phase 4.4 gave for
budgets.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import Float, case, func, select
from sqlalchemy.orm import Session

from app.behavior.signals import (
    CAP_TERMINATIONS,
    RULES,
    SignalResult,
    WindowMetrics,
    thresholds_for,
)
from app.behavior.states import REPORTABLE_STATES, SignalState
from app.models.agent import Agent
from app.models.runtime import (
    AgentDeployment,
    AgentExecution,
    AgentVersion,
    BehavioralFinding,
    Environment,
    Tool,
    ToolCall,
)

logger = logging.getLogger(__name__)

# Statuses that count as an observed outcome. Identical to Phase 3.5's
# ``TERMINAL_FOR_HEALTH`` and imported from nowhere on purpose -- see
# ``test_ac05_the_terminal_status_set_matches_35``, which asserts the two are
# equal rather than letting a copy drift silently.
TERMINAL_FOR_BEHAVIOR: frozenset[str] = frozenset({
    "SUCCEEDED", "FAILED", "TIMED_OUT", "DEAD_LETTERED", "DENIED", "BLOCKED", "CANCELLED",
})
FAILURE_STATUSES: frozenset[str] = frozenset({"FAILED", "DEAD_LETTERED"})
TIMEOUT_STATUSES: frozenset[str] = frozenset({"TIMED_OUT"})
DENIAL_STATUSES: frozenset[str] = frozenset({"DENIED", "BLOCKED"})

DEFAULT_WINDOW = timedelta(days=7)
MAX_WINDOW = timedelta(days=90)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class EvaluationResult:
    agent_id: uuid.UUID
    window_start: datetime
    window_end: datetime
    baseline_start: datetime
    baseline_end: datetime
    candidate: WindowMetrics
    baseline: WindowMetrics | None
    results: tuple[SignalResult, ...]
    persisted: tuple[uuid.UUID, ...] = ()

    @property
    def reportable(self) -> tuple[SignalResult, ...]:
        return tuple(r for r in self.results if r.state in REPORTABLE_STATES)


class BehavioralEvaluator:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Aggregation
    # ------------------------------------------------------------------ #
    def _aggregate(self, organization_id: uuid.UUID, agent_id: uuid.UUID,
                   start: datetime, end: datetime) -> WindowMetrics:
        """One indexed pass over ``agent_executions``, plus one grouped pass
        each for terminations, error codes, models and tool calls.

        **Measured before writing (the 4.2/4.4 discipline).** At 115,381
        executions the agent-scoped window aggregate runs at **0.57ms p50**,
        and the plan is a ``BitmapAnd`` of the two indexes that already exist —
        ``ix_agent_executions_org_created`` and ``ix_agent_executions_agent`` —
        with no sequential scan. Postgres combines them, so a dedicated
        ``(agent_id, created_at)`` composite would buy nothing measurable and
        this phase adds no index. The tenant predicate leads, so the query
        cannot see another tenant's rows even for a colliding agent id."""
        counted = case((AgentExecution.status.in_(tuple(TERMINAL_FOR_BEHAVIOR)), 1), else_=0)
        scope = (
            AgentExecution.organization_id == organization_id,
            AgentExecution.agent_id == agent_id,
            AgentExecution.created_at >= start,
            AgentExecution.created_at <= end,
        )
        row = self.db.execute(
            select(
                func.coalesce(func.sum(counted), 0),
                func.coalesce(func.sum(case((AgentExecution.status == "SUCCEEDED", 1), else_=0)), 0),
                func.coalesce(func.sum(case(
                    (AgentExecution.status.in_(tuple(FAILURE_STATUSES)), 1), else_=0)), 0),
                func.coalesce(func.sum(case(
                    (AgentExecution.status.in_(tuple(TIMEOUT_STATUSES)), 1), else_=0)), 0),
                func.coalesce(func.sum(case(
                    (AgentExecution.status.in_(tuple(DENIAL_STATUSES)), 1), else_=0)), 0),
                func.avg(AgentExecution.duration_ms),
                func.percentile_cont(0.95).within_group(
                    AgentExecution.duration_ms.cast(Float).asc()),
                func.avg(AgentExecution.cost_amount),
                func.coalesce(func.sum(AgentExecution.cost_amount), 0),
                func.avg(AgentExecution.loop_iterations),
            ).where(*scope)
        ).one()

        sample_count = int(row[0] or 0)
        if not sample_count:
            return WindowMetrics()

        terminations: dict[str, int] = {}
        for reason, count in self.db.execute(
            select(AgentExecution.termination_reason, func.count())
            .where(*scope, AgentExecution.termination_reason.is_not(None))
            .group_by(AgentExecution.termination_reason)
        ):
            terminations[reason] = int(count)

        error_codes: dict[str, int] = {}
        for code, count in self.db.execute(
            select(AgentExecution.error_code, func.count())
            .where(*scope, AgentExecution.error_code.is_not(None))
            .group_by(AgentExecution.error_code)
        ):
            error_codes[code] = int(count)

        # Model and provider attribution (M4-4.5-FR-020). Read from the
        # version's frozen `model_configuration`, which is what the execution
        # actually ran under -- never from the agent's current configuration,
        # which may have changed since.
        models: dict[str, int] = {}
        providers: dict[str, int] = {}
        for configuration, count in self.db.execute(
            select(AgentVersion.model_configuration, func.count())
            .join(AgentExecution, AgentExecution.agent_version_id == AgentVersion.id)
            .where(*scope).group_by(AgentVersion.model_configuration)
        ):
            configuration = configuration or {}
            if configuration.get("model"):
                models[configuration["model"]] = models.get(configuration["model"], 0) + int(count)
            if configuration.get("provider"):
                providers[configuration["provider"]] = (
                    providers.get(configuration["provider"], 0) + int(count))

        return WindowMetrics(
            sample_count=sample_count,
            succeeded=int(row[1] or 0), failed=int(row[2] or 0),
            timed_out=int(row[3] or 0), denied=int(row[4] or 0),
            avg_duration_ms=float(row[5]) if row[5] is not None else None,
            p95_duration_ms=float(row[6]) if row[6] is not None else None,
            avg_cost=float(row[7]) if row[7] is not None else None,
            total_cost=float(row[8] or 0),
            avg_loop_iterations=float(row[9]) if row[9] is not None else None,
            cap_terminations=sum(v for k, v in terminations.items() if k in CAP_TERMINATIONS),
            termination_reasons=terminations, error_codes=error_codes,
            models=models, providers=providers,
            tools=self._tool_metrics(agent_id, start, end),
        )

    def _tool_metrics(self, agent_id: uuid.UUID, start: datetime,
                      end: datetime) -> dict[str, tuple[int, int, str]]:
        """Per-tool call and failure counts.

        A tool call is a failure when it carries an ``error_code``/``error_class``
        or its status is not ``ALLOWED`` — the same fields Phase 5.6a.2's
        resilience layer writes, never a second notion of "did this tool
        work"."""
        failed = case(
            ((ToolCall.error_code.is_not(None)) | (ToolCall.error_class.is_not(None))
             | (ToolCall.status != "ALLOWED"), 1), else_=0)
        rows = self.db.execute(
            select(ToolCall.tool_id, func.count(ToolCall.id),
                   func.coalesce(func.sum(failed), 0), Tool.name)
            .join(Tool, Tool.id == ToolCall.tool_id)
            .where(ToolCall.agent_id == agent_id,
                   ToolCall.created_at >= start, ToolCall.created_at <= end)
            .group_by(ToolCall.tool_id, Tool.name)
        ).all()
        return {str(tool_id): (int(calls), int(failures), name)
                for tool_id, calls, failures, name in rows}

    # ------------------------------------------------------------------ #
    # Veto (step 1)
    # ------------------------------------------------------------------ #
    def _veto_reason(self, agent: Agent) -> str | None:
        """Read from the *same* field the kill switch writes — never a second
        notion of "is this agent stopped"."""
        if agent.lifecycle_status == "SUSPENDED":
            return ("the agent is suspended, so its recent executions describe the "
                    "intervention rather than its behavior")
        if agent.lifecycle_status in ("ARCHIVED", "DEPRECATED"):
            return f"the agent is {agent.lifecycle_status.lower()} and no longer running"
        return None

    # ------------------------------------------------------------------ #
    # Evaluate (steps 1 → 4)
    # ------------------------------------------------------------------ #
    def evaluate(self, *, organization_id: uuid.UUID, agent: Agent,
                 window_end: datetime | None = None,
                 window: timedelta = DEFAULT_WINDOW,
                 environment: Environment | None = None,
                 persist: bool = True) -> EvaluationResult:
        """Order matters and is Phase 3.5's, for Phase 3.5's reasons."""
        window_end = window_end or _now()
        if window > MAX_WINDOW:
            window = MAX_WINDOW
        window_start = window_end - window
        baseline_end, baseline_start = window_start, window_start - window
        thresholds = thresholds_for(environment.policy if environment else None)

        # (1) Veto.
        veto = self._veto_reason(agent)
        if veto is not None:
            results = tuple(
                SignalResult(signal_type=rule.__name__, metric="n/a",
                             state=SignalState.UNKNOWN,
                             reason=f"Not evaluable: {veto}.")
                for rule in RULES
            )
            result = EvaluationResult(
                agent_id=agent.id, window_start=window_start, window_end=window_end,
                baseline_start=baseline_start, baseline_end=baseline_end,
                candidate=WindowMetrics(), baseline=None, results=results)
            return self._persist(result, organization_id, agent) if persist else result

        candidate = self._aggregate(organization_id, agent.id, window_start, window_end)

        # (2) Sufficiency. A thin window is never anomalous *and never normal*.
        minimum = int(thresholds["min_samples"])
        if candidate.sample_count < max(minimum, 1):
            reason = (
                f"Only {candidate.sample_count} executions in the window; at least "
                f"{max(minimum, 1)} are required before behavior can be judged. "
                "A thin sample is not evidence of a change."
            )
            results = tuple(
                SignalResult(signal_type=rule.__name__, metric="sample_count",
                             state=SignalState.INSUFFICIENT_DATA, reason=reason,
                             observed=float(candidate.sample_count),
                             threshold=float(max(minimum, 1)))
                for rule in RULES
            )
            result = EvaluationResult(
                agent_id=agent.id, window_start=window_start, window_end=window_end,
                baseline_start=baseline_start, baseline_end=baseline_end,
                candidate=candidate, baseline=None, results=results)
            return self._persist(result, organization_id, agent) if persist else result

        # A baseline that is itself too thin is *no baseline* rather than a
        # weak one: comparing against three executions would manufacture drift
        # out of noise. The absolute thresholds still apply, so the signal is
        # still evaluated -- just not relatively.
        baseline = self._aggregate(organization_id, agent.id, baseline_start, baseline_end)
        if baseline.sample_count < int(thresholds["min_baseline_samples"]):
            baseline = None

        # (3) Absolute thresholds, then (4) baseline -- inside each rule, in
        # that order. See `signals._rate_rule`.
        results = tuple(rule(candidate, baseline, thresholds) for rule in RULES)

        result = EvaluationResult(
            agent_id=agent.id, window_start=window_start, window_end=window_end,
            baseline_start=baseline_start, baseline_end=baseline_end,
            candidate=candidate, baseline=baseline, results=results)
        return self._persist(result, organization_id, agent) if persist else result

    # ------------------------------------------------------------------ #
    # Persistence (M4-4.5-FR-012), idempotent
    # ------------------------------------------------------------------ #
    def _persist(self, result: EvaluationResult, organization_id: uuid.UUID,
                 agent: Agent) -> EvaluationResult:
        """One window ⇒ one finding per signal (M4-4.5-FR-010, AC-10).

        The dedup key is ``(agent_id, signal_type, window_start, window_end)``,
        enforced by a unique index rather than by checking first: re-running an
        evaluation over the same window — which the Phase 3.8 scheduler will do
        whenever a run overlaps or retries — must not multiply findings. On
        conflict the existing row is left alone rather than updated, because
        the rules are deterministic: a second evaluation of the same window
        computes the same verdict, so there is nothing to update.

        ``NORMAL`` produces no row. Recording every quiet window would bury the
        ones that matter — the same materiality reasoning Phase 4.3 applied to
        governance decisions. ``INSUFFICIENT_DATA`` and ``UNKNOWN`` *do* persist,
        because "we could not tell" is the answer to a question an operator
        will otherwise keep asking."""
        from sqlalchemy.dialects.postgresql import insert

        version_id, environment_id = self._context_for(agent, result)
        persisted: list[uuid.UUID] = []

        for signal in result.reportable:
            row_id = uuid.uuid4()
            statement = insert(BehavioralFinding).values(
                id=row_id, organization_id=organization_id, agent_id=agent.id,
                agent_version_id=version_id, environment_id=environment_id,
                signal_type=signal.signal_type, state=signal.state.value,
                metric=signal.metric,
                window_start=result.window_start, window_end=result.window_end,
                sample_count=result.candidate.sample_count,
                observed_value=signal.observed, threshold_value=signal.threshold,
                baseline_value=signal.baseline,
                attribution=self._attribution(signal),
                explanation=self._explanation(signal, result),
            ).on_conflict_do_nothing(
                index_elements=["agent_id", "signal_type", "window_start", "window_end"])
            self.db.execute(statement)
            persisted.append(row_id)

        self.db.commit()
        return EvaluationResult(
            agent_id=result.agent_id, window_start=result.window_start,
            window_end=result.window_end, baseline_start=result.baseline_start,
            baseline_end=result.baseline_end, candidate=result.candidate,
            baseline=result.baseline, results=result.results,
            persisted=tuple(persisted))

    def _context_for(self, agent: Agent,
                     result: EvaluationResult) -> tuple[uuid.UUID | None, uuid.UUID | None]:
        """The version and environment most of the window ran under.

        Attribution, not identity: a window can span a version change, and
        recording the dominant one is more useful than recording none. The
        finding's ``attribution`` carries the full model/provider breakdown, so
        nothing is lost by naming a single row here."""
        row = self.db.execute(
            select(AgentExecution.agent_version_id, AgentExecution.deployment_id,
                   func.count(AgentExecution.id).label("n"))
            .where(AgentExecution.agent_id == agent.id,
                   AgentExecution.created_at >= result.window_start,
                   AgentExecution.created_at <= result.window_end)
            .group_by(AgentExecution.agent_version_id, AgentExecution.deployment_id)
            .order_by(func.count(AgentExecution.id).desc()).limit(1)
        ).first()
        if row is None:
            return None, None
        environment_id = None
        if row[1] is not None:
            deployment = self.db.get(AgentDeployment, row[1])
            environment_id = deployment.environment_id if deployment else None
        return row[0], environment_id

    @staticmethod
    def _attribution(signal: SignalResult) -> dict:
        """M4-4.5-FR-020/021 — what the data can name, and one thing it cannot.

        ``connector`` is present and permanently null. That is deliberate: the
        runtime has no vocabulary for *which external system a version depends
        on* (ACT-INT-FR-006, the runtime-never-knows boundary that Phases 3.2,
        3.3 and 3.5 each reported in turn), so "which connector caused today's
        failures" cannot be answered without inventing a dependency link that
        does not exist. Naming the gap in every finding is more honest than
        omitting the key and letting a reader assume it was never considered."""
        return {
            **signal.attribution,
            "connector": None,
            "connector_attribution": "unavailable: no runtime-to-integration dependency link",
        }

    @staticmethod
    def _explanation(signal: SignalResult, result: EvaluationResult) -> dict:
        """M4-4.5-FR-011 — the finding must explain itself from its own record,
        with no external context. Everything an operator needs to recompute the
        verdict by hand is here: the metric, both window bounds, the sample
        counts, the observed value, what it was compared against, and the
        crossing in words."""
        return {
            "metric": signal.metric,
            "observed_value": signal.observed,
            "threshold_value": signal.threshold,
            "baseline_value": signal.baseline,
            "crossing": signal.reason,
            "window": {
                "start": result.window_start.isoformat(),
                "end": result.window_end.isoformat(),
                "sample_count": result.candidate.sample_count,
            },
            "baseline_window": {
                "start": result.baseline_start.isoformat(),
                "end": result.baseline_end.isoformat(),
                "sample_count": result.baseline.sample_count if result.baseline else 0,
            },
            "evidence": signal.evidence,
            "rule": "deterministic threshold/baseline comparison; no model, no scoring",
        }
