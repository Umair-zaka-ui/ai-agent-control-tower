"""The budget/enforcement seam (M4-4.4-FR-030..032).

**This module is the whole of Phase 4.4's contact with the execution path, and
it contains no code that stops an execution.** It reserves budget, reports what
is left, and settles afterwards. Whether an execution may continue is answered
in exactly one place on this platform — Phase 4.3's ``RuntimeGovernanceEngine``
— and that stays true here.

The division, stated once:

===================  ==================================================
Phase 4.4 (here)     Reserve, measure, reconcile, release. Produces a
                     *number*: how much headroom is left.
Phase 4.3 (engine)   Reads that number at a checkpoint and returns
                     ALLOW / DENY / CHALLENGE / STOP.
===================  ==================================================

A refused reservation is therefore not a refused execution. It is a budget with
no headroom, reported as such, which the engine turns into a ``STOP`` carrying
``BUDGET_EXCEEDED`` at the very first checkpoint — before any model call. The
observable outcome is the same as if this module had stopped it; the difference
is that there is still only one thing that can.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.runtime import (
    AgentDeployment,
    AgentExecution,
    AgentVersion,
    Budget,
    ExecutionMessage,
)
from app.finops.budgets import BudgetService, ExecutionScope
from app.finops.reservations import RESERVING_MODES, ReservationService, period_key

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BudgetConstraint:
    """What the governance engine is handed. Deliberately a plain value: the
    engine cannot reach back through it to change a budget, take a
    reservation, or discover anything beyond the headroom it needs to decide
    with."""

    budget_id: uuid.UUID
    name: str
    mode: str
    remaining: float
    currency: str
    over_threshold: bool

    @classmethod
    def none(cls) -> "BudgetConstraint | None":
        return None


class BudgetGuard:
    """Reserve before, settle after."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Before the loop
    # ------------------------------------------------------------------ #
    def prepare(self, execution: AgentExecution, *, agent: Agent | None = None,
                version: AgentVersion | None = None,
                deployment: AgentDeployment | None = None) -> BudgetConstraint | None:
        """Resolve applicable budgets, take reservations, and report the
        binding one.

        Returns the **tightest** constraint — the budget with the least
        headroom, and a refusal in preference to any amount of headroom. When
        several budgets apply, an execution has to satisfy all of them, so the
        one that will stop it first is the one worth telling the engine about;
        reporting a roomier budget would produce a decision whose message named
        the wrong ceiling.

        Never raises for an ordinary budget outcome. A budget failure that is
        *not* ordinary — the store being unreachable — is deliberately allowed
        to propagate to the caller's own fail-closed handling rather than being
        swallowed here into "no budget applies", which would silently disable
        every ceiling in the organization the moment the table was slow.
        """
        scope = ExecutionScope(
            organization_id=execution.organization_id,
            agent_id=execution.agent_id,
            project_id=agent.project_id if agent else None,
            environment=deployment.environment if deployment else None,
            environment_id=deployment.environment_id if deployment else None,
            model=(version.model_configuration or {}).get("model") if version else None,
        )
        budgets = BudgetService(self.db).resolve(scope)
        if not budgets:
            return None

        reservations = ReservationService(self.db)
        binding: BudgetConstraint | None = None

        for budget in budgets:
            state = reservations.state(
                budget, key=period_key(budget.period, execution.id))
            if budget.mode not in RESERVING_MODES:
                # INFORMATIONAL / WARNING: observe and signal, never reach the
                # engine. FR-032 by construction -- there is no path from here
                # to a constraint for these modes.
                self._signal(budget, self._observed_state(budget, execution), execution)
                continue

            held = reservations.reserve(budget, execution)
            if held is None:
                # No headroom. Report zero remaining; the engine stops it.
                candidate = BudgetConstraint(
                    budget_id=budget.id, name=budget.name, mode=budget.mode,
                    remaining=min(state.remaining, 0.0), currency=budget.currency,
                    over_threshold=True)
            else:
                after = reservations.state(
                    budget, key=period_key(budget.period, execution.id))
                candidate = BudgetConstraint(
                    budget_id=budget.id, name=budget.name, mode=budget.mode,
                    remaining=after.remaining, currency=budget.currency,
                    over_threshold=after.over_threshold)
                self._signal(budget, after, execution)

            if binding is None or candidate.remaining < binding.remaining:
                binding = candidate

        return binding

    # ------------------------------------------------------------------ #
    # After the loop
    # ------------------------------------------------------------------ #
    def settle(self, execution: AgentExecution) -> None:
        """Reconcile every hold this execution took to what it actually spent.

        **A failed execution's spend is real spend.** ``cost_amount`` is only
        written on the success path, so a loop that burned three turns of
        tokens and then hit a cap would look free if this trusted that column
        alone. The per-turn figures are on the transcript
        (``execution_messages.cost_amount``, written by ``PricingService`` at
        the time of each call), so the fallback sums those — the same numbers,
        recorded earlier.

        Spending nothing releases the hold outright rather than reconciling it
        to zero. Both give the money back; ``RELEASED`` says *this execution
        never spent*, which is a different fact from *this execution cost
        nothing*, and the distinction is worth keeping in the ledger."""
        actual = self._actual_spend(execution)
        service = ReservationService(self.db)
        if actual > 0:
            service.reconcile(execution, actual_amount=actual)
        else:
            service.release(execution.id, reason="no spend recorded")

    def _actual_spend(self, execution: AgentExecution) -> float:
        if execution.cost_amount is not None:
            return float(execution.cost_amount)
        total = self.db.execute(
            select(func.coalesce(func.sum(ExecutionMessage.cost_amount), 0)).where(
                ExecutionMessage.execution_id == execution.id)
        ).scalar_one()
        return float(total or 0.0)

    # ------------------------------------------------------------------ #
    # Utilization for the modes that keep no ledger
    # ------------------------------------------------------------------ #
    def _observed_state(self, budget: Budget, execution: AgentExecution):
        """Where a signalling budget's "spent" figure comes from.

        **Two accounting sources, and the split is deliberate rather than an
        oversight.** An enforcing budget (HARD_LIMIT / APPROVAL_REQUIRED) is
        accounted from its *reservation ledger*, because that is the only thing
        you can safely reserve against: you cannot atomically claim a share of
        a number you compute by scanning a table. A signalling budget
        (INFORMATIONAL / WARNING) takes no reservations at all -- deliberately,
        since holding budget for a mode that will never refuse anything would
        slow the execution path to enforce nothing -- so its ledger is empty
        and would report 0% forever. It reads real spend from
        ``agent_executions`` instead, which is the authoritative source either
        way.

        The consequence, stated because someone will meet it: a budget switched
        from WARNING to HARD_LIMIT starts its ledger at that moment, so its
        utilization drops to what has been reserved since. That is the honest
        behaviour -- a budget governs from when it began governing -- but it
        will surprise an operator who expects the number to carry over, and it
        is documented in ``docs/runtime/budgets.md`` for exactly that reason.
        """
        from app.finops.aggregation import CostAggregator, CostFilters
        from app.finops.reservations import BudgetState

        start, end = self._period_bounds(budget)
        filters = CostFilters(started_after=start, started_before=end)
        if budget.scope_type == "AGENT":
            filters = replace(filters, agent_id=budget.scope_id)
        elif budget.scope_type == "PROJECT":
            filters = replace(filters, project_id=budget.scope_id)
        elif budget.scope_type == "ENVIRONMENT":
            filters = replace(filters, environment=budget.scope_value)
        elif budget.scope_type == "MODEL":
            filters = replace(filters, model=budget.scope_value)

        summary = CostAggregator(self.db).summary(budget.organization_id, filters=filters)
        return BudgetState(
            budget_id=budget.id, mode=budget.mode, period=budget.period,
            period_key=period_key(budget.period, execution.id),
            limit_amount=float(budget.limit_amount), reserved=0.0,
            spent=summary.actual_amount, currency=budget.currency,
            threshold_percent=budget.threshold_percent,
        )

    @staticmethod
    def _period_bounds(budget: Budget) -> tuple[datetime, datetime]:
        """The calendar window a signalling budget observes. An
        EXECUTION-period budget has no window of its own, so it observes the
        day -- the narrowest calendar bucket this platform has."""
        now = datetime.now(timezone.utc)
        if budget.period == "MONTHLY":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now

    # ------------------------------------------------------------------ #
    # Signals (FR-032)
    # ------------------------------------------------------------------ #
    def _signal(self, budget: Budget, state, execution: AgentExecution) -> None:
        """A threshold crossing is a durable audit signal and nothing else.

        Not a notification: Slack and email delivery are explicitly out of
        scope for this phase, and an alerting system that quietly did half of
        itself would be worse than one that is honestly absent. Not a block
        either — for ``INFORMATIONAL`` and ``WARNING`` there is no path from
        this method to the engine at all."""
        if not state.over_threshold:
            return
        try:
            from app.authorization.enums import AuthorizationAuditEvent
            from app.runtime.services import _record_event

            _record_event(
                self.db, AuthorizationAuditEvent.RUNTIME_BUDGET_THRESHOLD_REACHED, None,
                organization_id=execution.organization_id, agent_id=execution.agent_id,
                execution_id=execution.id,
                severity="WARNING" if budget.mode == "WARNING" else "INFO",
                meta={
                    "budget_id": str(budget.id), "budget_name": budget.name,
                    "mode": budget.mode, "period_key": state.period_key,
                    "utilization_percent": round(state.utilization * 100, 2),
                    "threshold_percent": budget.threshold_percent,
                },
            )
        except Exception as exc:  # noqa: BLE001
            # A signal is an observation. Failing to record one must not fail
            # the execution that triggered it -- the fail-open posture belongs
            # to signals, exactly as it does to telemetry (§9).
            logger.warning("Budget threshold signal failed for budget %s: %s", budget.id, exc)
