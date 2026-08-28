"""Reserve-then-reconcile (M4-4.4-FR-020..024) — **the §35 concurrency gate.**

## The failure this exists to prevent

Twenty workers each read *"$9 remaining"* against a $10 budget, each conclude
they may spend $9, and $180 is spent against a $10 budget. Nothing in the code
looked wrong: every worker read a true balance and acted on it correctly. The
bug is the gap between the read and the act — and on this platform that gap
contains a model call, so it is not small.

## The mechanism, exactly

``reserve()`` runs this sequence in **one transaction**:

1. ``SELECT ... FROM budgets WHERE id = :id FOR UPDATE`` — every concurrent
   claimant against this budget now queues here, in the database, across
   processes and machines. §11 forbids an in-process lock explicitly, and the
   Phase 3.9 worker fleet would make one worthless anyway.
2. Sum ``reserved_amount`` over ``RESERVED`` rows plus ``actual_amount`` over
   ``RECONCILED`` rows for this ``period_key`` — an index-only read of
   ``ix_budget_reservations_period``.
3. If ``committed + estimate > limit``, refuse. Otherwise insert the
   reservation.
4. Commit — releasing the lock. **Nothing below this point holds it**, which
   is the commit-before-dispatch rule (§9) applied to money: the budget row is
   not locked across the model call the reservation was taken for.

The lock is held for two indexed statements. It is not held across any I/O.

## What is guaranteed, and what is not

This distinction is the honest core of the phase and it is stated in the docs,
in the ADR and in the tests rather than left for someone to discover.

**Guaranteed:** the sum of *reserved* amounts never exceeds the limit. Two
workers cannot both consume the same remaining allowance — step 1 serializes
them and step 3 is evaluated against a balance that already includes the other
claimant's hold. This is the §35 property, and it is proven with real separate
Postgres sessions.

**Not guaranteed:** that *actual* spend never exceeds the limit. A model call's
cost is unknowable until it returns, so an execution admitted with a $0.10 hold
that turns out to cost $0.14 overshoots by $0.04. The overshoot is bounded by
the sum of (actual − reserved) across executions in flight, and it is bounded
*per execution* by Phase 4.3's ``min_remaining_cost`` headroom rule, which
stops a loop before dispatching an iteration the remaining budget could not
absorb.

Claiming the second guarantee would require knowing a price before paying it.
A system that claimed it would be lying, and the lie would be discovered in
exactly the situation the budget was bought for.

## Idempotency and orphans

A partial unique index on ``(budget_id, execution_id) WHERE status <>
'RELEASED'`` makes a double-reserve a database error rather than an
application-level promise. A retried attempt claims afresh only because its
predecessor's reservation was *released* first — which is what makes orphan
release a correctness requirement rather than tidiness: a reservation that
leaked would permanently shrink a tenant's budget every time a worker died.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.identity.errors import ErrorCode, IdentityError
from app.models.runtime import AgentExecution, Budget, BudgetReservation

logger = logging.getLogger(__name__)

RESERVED = "RESERVED"
RECONCILED = "RECONCILED"
RELEASED = "RELEASED"

# Modes that take a reservation at all. INFORMATIONAL and WARNING observe and
# signal; holding budget for a mode that will never refuse anything would slow
# the execution path to enforce nothing.
RESERVING_MODES = frozenset({"HARD_LIMIT", "APPROVAL_REQUIRED"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def period_key(period: str, execution_id: uuid.UUID, *, at: datetime | None = None) -> str:
    """The bucket a reservation counts against.

    ``EXECUTION`` period gives every execution its own bucket, so a
    per-execution ceiling is expressed by the same summation as a daily or
    monthly one rather than by a second code path."""
    moment = at or _now()
    if period == "DAILY":
        return moment.strftime("%Y-%m-%d")
    if period == "MONTHLY":
        return moment.strftime("%Y-%m")
    return str(execution_id)


@dataclass(frozen=True)
class BudgetState:
    """What a budget looks like right now: what is committed against it, and
    what is left. ``reserved`` and ``spent`` are reported separately because
    they answer different questions — one is money that might yet be released,
    the other is money that is gone."""

    budget_id: uuid.UUID
    mode: str
    period: str
    period_key: str
    limit_amount: float
    reserved: float
    spent: float
    currency: str
    threshold_percent: int

    @property
    def committed(self) -> float:
        return self.reserved + self.spent

    @property
    def remaining(self) -> float:
        return self.limit_amount - self.committed

    @property
    def utilization(self) -> float:
        if self.limit_amount <= 0:
            return 1.0
        return self.committed / self.limit_amount

    @property
    def over_threshold(self) -> bool:
        return self.utilization * 100 >= self.threshold_percent

    def as_dict(self) -> dict:
        return {
            "budget_id": str(self.budget_id),
            "mode": self.mode,
            "period": self.period,
            "period_key": self.period_key,
            "limit_amount": round(self.limit_amount, 8),
            "reserved": round(self.reserved, 8),
            "spent": round(self.spent, 8),
            "committed": round(self.committed, 8),
            "remaining": round(self.remaining, 8),
            "utilization_percent": round(self.utilization * 100, 4),
            "threshold_percent": self.threshold_percent,
            "over_threshold": self.over_threshold,
            "currency": self.currency,
        }


class ReservationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ #
    # Balance
    # ------------------------------------------------------------------ #
    def state(self, budget: Budget, *, key: str) -> BudgetState:
        """Committed and remaining for one budget in one period.

        ``RESERVED`` rows count their held estimate; ``RECONCILED`` rows count
        their *actual*. ``RELEASED`` rows count nothing, which is what makes
        releasing an orphan give the money back."""
        row = self.db.execute(
            select(
                func.coalesce(func.sum(case(
                    (BudgetReservation.status == RESERVED, BudgetReservation.reserved_amount),
                    else_=0)), 0).label("reserved"),
                func.coalesce(func.sum(case(
                    (BudgetReservation.status == RECONCILED,
                     func.coalesce(BudgetReservation.actual_amount, 0)),
                    else_=0)), 0).label("spent"),
            ).where(
                BudgetReservation.budget_id == budget.id,
                BudgetReservation.period_key == key,
            )
        ).one()
        return BudgetState(
            budget_id=budget.id, mode=budget.mode, period=budget.period, period_key=key,
            limit_amount=float(budget.limit_amount), reserved=float(row.reserved),
            spent=float(row.spent), currency=budget.currency,
            threshold_percent=budget.threshold_percent,
        )

    def estimate_for(self, budget: Budget) -> float:
        if budget.reservation_estimate is not None:
            return float(budget.reservation_estimate)
        return float(settings.BUDGET_DEFAULT_RESERVATION)

    # ------------------------------------------------------------------ #
    # Reserve
    # ------------------------------------------------------------------ #
    def reserve(self, budget: Budget, execution: AgentExecution, *,
                amount: float | None = None) -> BudgetReservation | None:
        """Atomically claim budget for this execution, or return ``None``.

        ``None`` means *refused, because the budget cannot cover the hold* —
        an ordinary answer, not an error, and deliberately not an exception:
        the caller's job is to report the refusal to the Phase 4.3 governance
        engine, which is the only thing on this platform that decides whether
        an execution may continue. Raising here would make this method look
        like a second enforcement path even though it is not one.

        **This method commits.** It has to: the point of a reservation is that
        the *next* worker sees it, and a worker in another process sees only
        committed rows. Committing also releases the ``FOR UPDATE`` before the
        caller does anything slow, which is the commit-before-dispatch rule
        applied to the budget row."""
        if budget.mode not in RESERVING_MODES or not budget.enabled:
            return None

        key = period_key(budget.period, execution.id)
        estimate = float(amount if amount is not None else self.estimate_for(budget))

        # (1) Serialize every concurrent claimant against this budget, in the
        #     database. Everything from here to the commit is two indexed
        #     statements; no I/O happens under this lock.
        locked = self.db.execute(
            select(Budget).where(Budget.id == budget.id).with_for_update()
        ).scalars().first()
        if locked is None:
            return None

        # (2) The balance, read *inside* the lock so a concurrent claimant's
        #     hold is already visible in it.
        state = self.state(locked, key=key)

        # (3) Refuse rather than overspend.
        if state.committed + estimate > state.limit_amount:
            self.db.rollback()
            return None

        reservation = BudgetReservation(
            budget_id=locked.id, execution_id=execution.id,
            organization_id=execution.organization_id, reserved_amount=estimate,
            status=RESERVED, period_key=key, currency=locked.currency,
        )
        self.db.add(reservation)
        try:
            # (4) Commit releases the lock. The caller may now do slow things.
            self.db.commit()
        except IntegrityError:
            # The partial unique index refused a second live reservation for
            # this (budget, execution). That is the idempotency guarantee
            # firing, not a failure: a retry that raced its own predecessor
            # must not double-hold.
            self.db.rollback()
            logger.info("Budget reservation already held for execution %s on budget %s",
                        execution.id, budget.id)
            return self.existing(budget.id, execution.id)
        self.db.refresh(reservation)
        return reservation

    def existing(self, budget_id: uuid.UUID, execution_id: uuid.UUID) -> BudgetReservation | None:
        return self.db.execute(
            select(BudgetReservation).where(
                BudgetReservation.budget_id == budget_id,
                BudgetReservation.execution_id == execution_id,
                BudgetReservation.status != RELEASED,
            )
        ).scalars().first()

    # ------------------------------------------------------------------ #
    # Reconcile / release
    # ------------------------------------------------------------------ #
    def reconcile(self, execution: AgentExecution, *, actual_amount: float | None) -> int:
        """M4-4.4-FR-021 — replace every hold for this execution with what it
        actually cost.

        Over-reservation is released implicitly: a ``RECONCILED`` row counts
        its ``actual_amount``, so the difference stops being committed the
        moment the status changes. Under-reservation is charged for the same
        reason — the actual is what counts, whatever was held.

        Idempotent by filtering on ``status == RESERVED``: a second call finds
        nothing to reconcile and changes nothing, so a retried worker cannot
        charge a budget twice."""
        rows = list(self.db.execute(
            select(BudgetReservation).where(
                BudgetReservation.execution_id == execution.id,
                BudgetReservation.status == RESERVED,
            )
        ).scalars())
        for row in rows:
            row.actual_amount = float(actual_amount or 0.0)
            row.status = RECONCILED
            row.reconciled_at = _now()
        if rows:
            self.db.flush()
        return len(rows)

    def release(self, execution_id: uuid.UUID, *, reason: str = "released") -> int:
        """M4-4.4-FR-023 — give the hold back.

        Called when an execution ends without spending what it held: a failure
        before the first model call, a cancellation, a kill switch, or a worker
        that died and had its lease reaped. A reservation that leaked would
        permanently shrink a tenant's budget every time a worker crashed, which
        turns an availability incident into a financial one."""
        rows = list(self.db.execute(
            select(BudgetReservation).where(
                BudgetReservation.execution_id == execution_id,
                BudgetReservation.status == RESERVED,
            )
        ).scalars())
        for row in rows:
            row.status = RELEASED
            row.reconciled_at = _now()
        if rows:
            self.db.flush()
            logger.info("Released %d budget reservation(s) for execution %s (%s)",
                        len(rows), execution_id, reason)
        return len(rows)

    def sweep_orphans(self, *, organization_id: uuid.UUID | None = None) -> int:
        """The safety net beneath ``release``.

        Every ordinary path releases its own reservation. This exists for the
        paths that do not get to run: a process killed between the reservation
        commit and the execution's terminal write. It finds reservations still
        ``RESERVED`` whose execution has already reached a terminal state, and
        releases them.

        Deliberately not time-based. A reservation is not orphaned because it
        is old — a long execution legitimately holds one for its whole run —
        it is orphaned because *the execution it belongs to has finished and it
        was not reconciled*. Using an age threshold would release live holds
        under exactly the load that made them slow, which is the opposite of
        what a budget guard should do when a tenant is busy."""
        from app.runtime.services import TERMINAL_EXECUTION_STATUSES

        stmt = (
            select(BudgetReservation)
            .join(AgentExecution, AgentExecution.id == BudgetReservation.execution_id)
            .where(
                BudgetReservation.status == RESERVED,
                AgentExecution.status.in_(tuple(TERMINAL_EXECUTION_STATUSES)),
            )
        )
        if organization_id is not None:
            stmt = stmt.where(BudgetReservation.organization_id == organization_id)

        rows = list(self.db.execute(stmt).scalars())
        for row in rows:
            row.status = RELEASED
            row.reconciled_at = _now()
        if rows:
            self.db.commit()
            logger.warning("Swept %d orphaned budget reservation(s)", len(rows))
        return len(rows)


def require_positive_amount(value: float) -> float:
    if value < 0:
        raise IdentityError(ErrorCode.BUDGET_INVALID, "A budget amount cannot be negative.")
    return value
