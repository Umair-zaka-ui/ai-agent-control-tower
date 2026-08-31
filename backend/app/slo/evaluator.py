"""Phase 4.7 -- deterministic, explainable SLO evaluation (M4-4.7-FR-002..004,
Gate J).

**The 3.5 / 4.5 shape, applied to an objective:**

1. **Veto.** An AGENT-scoped SLO whose agent is suspended or archived is
   ``UNKNOWN`` before a row is aggregated -- its recent data describes the
   intervention, not the objective. (An ORGANIZATION/ENVIRONMENT SLO has no
   single subject to veto.)
2. **Sufficiency.** Below :data:`~app.slo.definitions.MIN_SAMPLES` terminal
   samples the answer is ``INSUFFICIENT_DATA`` -- neither ``MET`` nor
   ``BREACHED``. "No failures observed" is not "the objective is met".
3. **Objective.** Compare the observed value to the target, in the direction
   fixed by the SLI (``higher_better`` → ``observed >= target``;
   ``lower_better`` → ``observed <= target``).
4. **Budget.** The error budget is the allowed "bad fraction" over the window.
   ``budget_consumed = bad_fraction / error_budget``; a value above 1.0 means
   the objective is violated and the budget for this window is spent.
   ``budget_remaining = max(0, 1 - budget_consumed)``.

Every number is a pure function of the rows in the window and the SLO's own
fields. Same rows, same window ⇒ same verdict. No model, no scoring, no
randomness -- a test asserts a full evaluation run three times is byte-identical.

Persistence is idempotent: ``(slo_id, window_start, window_end)`` is unique, and
a re-run over the same window is a no-op (``on_conflict_do_nothing``), so the
3.8 scheduler can drive this without producing duplicate rows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.runtime import SLODefinition, SLOEvaluation
from app.slo.definitions import MIN_SAMPLES, WINDOWS
from app.slo.sli import SLI_SPECS, SLIComputer, SLIResult
from app.slo.states import SLOState


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class SLOEvaluationResult:
    slo_id: uuid.UUID
    organization_id: uuid.UUID
    sli: str
    scope_type: str
    scope_id: uuid.UUID | None
    window_start: datetime
    window_end: datetime
    target: float
    error_budget: float
    observed_value: float | None
    sample_count: int
    state: SLOState
    budget_consumed: float | None
    budget_remaining: float | None
    explanation: dict
    evaluation_id: uuid.UUID | None = None
    #: True when this evaluation persisted a new row (vs a dedup no-op).
    persisted: bool = False

    @property
    def breached(self) -> bool:
        return self.state is SLOState.BREACHED

    @property
    def met(self) -> bool:
        return self.state is SLOState.MET


class SLOEvaluator:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._sli = SLIComputer(db)

    # ------------------------------------------------------------------ #
    def evaluate(self, slo: SLODefinition, *, window_end: datetime | None = None,
                 persist: bool = True) -> SLOEvaluationResult:
        window_end = window_end or _now()
        window_start = window_end - WINDOWS[slo.window]
        target = float(slo.target)
        error_budget = float(slo.error_budget)
        direction, unit = SLI_SPECS[slo.sli]

        # (1) Veto.
        veto = self._veto(slo)
        if veto is not None:
            return self._result(slo, window_start, window_end, target, error_budget,
                                observed=None, sample_count=0, state=SLOState.UNKNOWN,
                                budget_consumed=None, budget_remaining=None,
                                explanation=self._explain(slo, window_start, window_end,
                                                          None, 0, error_budget, None,
                                                          f"Not evaluable: {veto}"),
                                persist=persist)

        sli_result: SLIResult = self._sli.compute(
            slo.sli, organization_id=slo.organization_id,
            window_start=window_start, window_end=window_end,
            scope_type=slo.scope_type, scope_id=slo.scope_id,
            latency_target_ms=target if unit == "ms" else None,
        )

        # (2) Sufficiency.
        if sli_result.sample_count < MIN_SAMPLES:
            reason = (
                f"Only {sli_result.sample_count} samples in the {slo.window} window; "
                f"at least {MIN_SAMPLES} are required before the objective can be judged. "
                "A thin window is not evidence the objective is met."
            )
            return self._result(slo, window_start, window_end, target, error_budget,
                                observed=sli_result.observed_value,
                                sample_count=sli_result.sample_count,
                                state=SLOState.INSUFFICIENT_DATA,
                                budget_consumed=None, budget_remaining=None,
                                explanation=self._explain(slo, window_start, window_end,
                                                          sli_result.observed_value,
                                                          sli_result.sample_count,
                                                          error_budget, None, reason),
                                persist=persist)

        # (3) Objective + (4) budget.
        observed = sli_result.observed_value
        bad_fraction = sli_result.bad_fraction
        budget_consumed = round(bad_fraction / error_budget, 6) if error_budget > 0 else None
        budget_remaining = (round(max(0.0, 1.0 - budget_consumed), 6)
                            if budget_consumed is not None else None)

        if direction == "higher_better":
            met = observed is not None and observed >= target
            crossing = (
                f"observed {observed:.4f} {'meets' if met else 'is below'} the target {target:.4f}"
            )
        else:
            met = observed is not None and observed <= target
            unit_label = "ms" if unit == "ms" else ""
            crossing = (
                f"observed {observed:.2f}{unit_label} "
                f"{'is within' if met else 'exceeds'} the target {target:.2f}{unit_label}"
            )
        state = SLOState.MET if met else SLOState.BREACHED
        reason = (
            f"{slo.sli} over {slo.window}: {crossing}. "
            f"Error budget {error_budget:.4f} "
            f"({'spent' if (budget_consumed or 0) > 1 else 'partly consumed'}: "
            f"{(budget_consumed or 0) * 100:.1f}%)."
        )

        return self._result(slo, window_start, window_end, target, error_budget,
                            observed=observed, sample_count=sli_result.sample_count,
                            state=state, budget_consumed=budget_consumed,
                            budget_remaining=budget_remaining,
                            explanation=self._explain(slo, window_start, window_end,
                                                      observed, sli_result.sample_count,
                                                      error_budget, budget_consumed, reason,
                                                      bad_count=sli_result.bad_count),
                            persist=persist)

    def evaluate_all(self, organization_id: uuid.UUID, *,
                     window_end: datetime | None = None) -> list[SLOEvaluationResult]:
        slos = list(self.db.execute(
            select(SLODefinition).where(
                SLODefinition.organization_id == organization_id,
                SLODefinition.enabled.is_(True),
            ).order_by(SLODefinition.name)
        ).scalars())
        return [self.evaluate(slo, window_end=window_end) for slo in slos]

    # ------------------------------------------------------------------ #
    def _veto(self, slo: SLODefinition) -> str | None:
        if slo.scope_type != "AGENT" or slo.scope_id is None:
            return None
        agent = self.db.get(Agent, slo.scope_id)
        if agent is None:
            return "the scoped agent no longer exists."
        if agent.lifecycle_status == "SUSPENDED":
            return "the scoped agent is suspended (kill switch or lifecycle suspension)."
        if agent.lifecycle_status in ("ARCHIVED", "DEPRECATED"):
            return f"the scoped agent is {agent.lifecycle_status.lower()} and no longer running."
        return None

    def _explain(self, slo: SLODefinition, ws: datetime, we: datetime,
                 observed: float | None, sample_count: int, error_budget: float,
                 budget_consumed: float | None, crossing: str,
                 bad_count: int | None = None) -> dict:
        return {
            "sli": slo.sli,
            "target": float(slo.target),
            "window": slo.window,
            "window_start": ws.isoformat(),
            "window_end": we.isoformat(),
            "observed_value": observed,
            "sample_count": sample_count,
            "bad_count": bad_count,
            "error_budget": error_budget,
            "budget_consumed": budget_consumed,
            "min_samples": MIN_SAMPLES,
            "crossing": crossing,
            "scope": {"type": slo.scope_type,
                      "id": str(slo.scope_id) if slo.scope_id else None},
            "rule": "deterministic objective/budget comparison; no model, no scoring",
        }

    def _result(self, slo, ws, we, target, error_budget, *, observed, sample_count,
                state, budget_consumed, budget_remaining, explanation,
                persist: bool) -> SLOEvaluationResult:
        evaluation_id = None
        persisted = False
        if persist:
            evaluation_id, persisted = self._persist(
                slo, ws, we, observed, sample_count, state, budget_consumed,
                budget_remaining, explanation)
        return SLOEvaluationResult(
            slo_id=slo.id, organization_id=slo.organization_id, sli=slo.sli,
            scope_type=slo.scope_type, scope_id=slo.scope_id,
            window_start=ws, window_end=we, target=target, error_budget=error_budget,
            observed_value=observed, sample_count=sample_count, state=state,
            budget_consumed=budget_consumed, budget_remaining=budget_remaining,
            explanation=explanation, evaluation_id=evaluation_id, persisted=persisted)

    def _persist(self, slo, ws, we, observed, sample_count, state, budget_consumed,
                 budget_remaining, explanation) -> tuple[uuid.UUID, bool]:
        """Idempotent on ``(slo_id, window_start, window_end)``. A re-run over
        the same window is a no-op -- the verdict is deterministic, so there is
        nothing to update."""
        row_id = uuid.uuid4()
        stmt = insert(SLOEvaluation).values(
            id=row_id, slo_id=slo.id, organization_id=slo.organization_id,
            window_start=ws, window_end=we, sample_count=sample_count,
            observed_value=observed, state=state.value,
            budget_consumed=budget_consumed, budget_remaining=budget_remaining,
            explanation=explanation,
        ).on_conflict_do_nothing(
            index_elements=["slo_id", "window_start", "window_end"]
        ).returning(SLOEvaluation.id)
        result = self.db.execute(stmt).scalar_one_or_none()
        if result is not None:
            self.db.commit()
            return result, True
        # Conflict: return the id of the row that already exists for this window.
        existing = self.db.execute(
            select(SLOEvaluation.id).where(
                SLOEvaluation.slo_id == slo.id,
                SLOEvaluation.window_start == ws,
                SLOEvaluation.window_end == we,
            )
        ).scalar_one()
        return existing, False
