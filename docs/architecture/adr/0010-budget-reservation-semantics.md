# ADR-0010 — Budgets are enforced by reservation, and the guarantee is about reservations

- **Status:** Accepted
- **Date:** 2026-08-28
- **Deciders:** Phase 4.4 (Milestone 4 — Runtime Governance & Observability)
- **Supersedes:** —

## Context

A budget that can be exceeded is not a budget. But the thing being budgeted —
the cost of a model call — **is unknowable until after it has been paid for**,
and this platform runs those calls from a fleet of worker processes that do not
share memory. Both facts are load-bearing, and together they rule out the
obvious design.

The obvious design is to check the balance before starting work:

```python
if spent_so_far() + estimate <= limit:
    run_the_execution()
```

This is wrong in the specific way concurrent systems are wrong. Twenty workers
each read *"$9 remaining"* against a $10 budget, each conclude they may spend
$9, and $180 is spent. Every worker read a true balance and acted on it
correctly. The defect is the gap between the read and the act — and on this
platform that gap contains a network call to a model provider, so it is not
small.

The forces:

1. **Cost is only known afterwards.** `agent_executions.cost_amount` is written
   when the execution completes, from token counts the provider returns.
   Nothing can know it in advance, and no amount of engineering changes that.
2. **Workers do not share memory.** Phase 3.9 built a real fleet. An
   in-process lock would pass a single-process test and fail the moment a
   second worker started — which is why §11 forbids one explicitly rather than
   leaving it to judgement.
3. **Phase 4.3 owns enforcement.** Its whole design rests on there being
   exactly one place that decides whether an execution may continue. A budget
   that stopped executions itself would be the second enforcement path 4.3
   exists to prevent.
4. **Budgets have to be adoptable.** An organization's first budget is almost
   never a hard limit. It is someone watching a number for a month to see
   whether the platform agrees with their finance team.
5. **Real cost already exists and is authoritative.** Phase 5.7a.3 computes it
   with effective-dated pricing and records the `pricing_version` that produced
   it. Nothing should recompute or copy that.

## Options considered

### Option A — Check the balance before each execution, no reservation
- Pros: trivial; no new table; no lock.
- Cons: the twenty-workers failure above. It is not a rare race — it is the
  normal behaviour of the design under any concurrency at all.

### Option B — Serialize every execution against a budget
- Pros: correct; simplest thing that is correct.
- Cons: a budget becomes a global mutex on throughput. One tenant's ceiling
  would serialize their entire fleet for the duration of every model call.

### Option C — Reserve an estimate, then reconcile to actual
- Pros: the claim is short and holds no lock across I/O; concurrent workers see
  each other's holds; over-reservation is returned automatically.
- Cons: needs a ledger table; needs an estimate that is necessarily wrong;
  needs orphan recovery when a worker dies holding one.

### Option D — Reserve, and additionally refuse to reconcile above the limit
- Pros: would let us claim total spend never exceeds the limit.
- Cons: **the claim would be false in the only way that matters.** Refusing to
  record a charge does not un-spend the money — the provider has already been
  paid. It would produce a ledger that disagrees with reality, which is worse
  than a ledger that reports an overshoot honestly.

## Decision

We chose **Option C**: an atomic reservation before the execution, reconciled
to actual afterwards, with the claim serialized by `SELECT ... FOR UPDATE` on
the budget row.

The sequence, in one transaction: lock the budget row; sum `RESERVED` holds
plus `RECONCILED` actuals for the period; refuse if the estimate would not fit;
otherwise insert the reservation; **commit**, releasing the lock before the
caller does anything slow. The lock is held for two indexed statements and
never across a model call — the commit-before-dispatch rule (§9) applied to
money.

**And we state the guarantee precisely, because Option D is the temptation to
overstate it:**

> **Guaranteed:** the sum of *reserved* amounts never exceeds the limit. Two
> workers cannot both consume the same remaining allowance.
>
> **Not guaranteed:** that *actual* spend never exceeds the limit. An execution
> admitted with a $0.25 hold that turns out to cost $0.40 overshoots by $0.15.
> The total overshoot is bounded by the sum of (actual − reserved) across
> executions in flight.

Claiming the second would require knowing a price before paying it. A system
that claimed it would be lying, and the lie would be discovered in exactly the
situation the budget was bought for. So the overshoot is documented, bounded,
and **has its own test** asserting it is real — rather than being a gap someone
finds in production.

Per-execution, the overshoot is separately bounded by Phase 4.3's
`min_remaining_cost` headroom rule, which stops a loop before dispatching an
iteration the remaining budget could not absorb.

**Two accounting sources, deliberately.** Enforcing budgets (HARD_LIMIT,
APPROVAL_REQUIRED) are accounted from the reservation ledger, because that is
the only thing you can atomically claim a share of. Signalling budgets
(INFORMATIONAL, WARNING) take no reservations — holding budget for a mode that
will never refuse anything would slow the execution path to enforce nothing —
so they observe real spend directly from `agent_executions`. Both read
authoritative data; they differ in *when*.

**Enforcement still runs through Phase 4.3.** A refused reservation is not a
refused execution. It is a budget with no headroom, reported as a number, which
the engine turns into a `STOP` carrying `BUDGET_EXCEEDED` at its first
checkpoint. `app/finops` contains no code that writes an execution's status,
asserted over the AST.

## Consequences

### Positive

- **Concurrent workers cannot overspend a budget**, proven with twelve real
  Postgres sessions racing a $1.00 budget at $0.25 a hold: exactly four are
  granted, every time.
- **Idempotency is the database's.** A partial unique index on
  `(budget_id, execution_id) WHERE status <> 'RELEASED'` makes a double-reserve
  an integrity error rather than an application-level promise — the same
  reasoning behind Phase 3.1's idempotency-key constraint, without needing its
  claim-then-poll machinery.
- **Over-reservation returns itself.** A `RECONCILED` row counts its actual, so
  the difference stops being committed the instant the status changes. No
  separate release step, and therefore no separate step that can be skipped.
- **The budget row is never locked across I/O**, so a slow provider cannot
  serialize a tenant's fleet.
- **No parallel cost store.** Reservations reference executions; the money
  stays on `agent_executions` where `PricingService` wrote it.

### Negative / accepted cost

- **Actual spend can exceed the limit**, by the bounded amount above. This is
  the honest cost of a price that is only knowable after payment, and it is the
  single most important thing for an operator to understand about this feature.
- **The reservation estimate is a guess, and its size is a real trade-off.**
  Hold too much and a tight budget admits fewer concurrent executions than it
  could afford; hold too little and more executions are in flight than the
  balance can cover if they all overrun. There is no correct default, only a
  small one (`BUDGET_DEFAULT_RESERVATION = 0.05`) and a per-budget override.
- **A budget switched from a signalling mode to an enforcing one starts its
  ledger at that moment**, so its reported utilization drops. That follows from
  the two accounting sources and is defensible — a budget governs from when it
  began governing — but it will surprise someone.
- **An enforcing budget adds a lock, two statements and a commit to the
  execution path**, on every execution it governs.
- **Orphan release is now a correctness requirement.** A leaked reservation
  permanently shrinks a tenant's budget, so a crashed worker becomes a
  financial incident rather than only an availability one. Handled on every
  terminal path plus a sweeper, but it is a new class of thing that can go
  wrong.

### Residual risk

- **The sweeper is not time-based, on purpose.** It releases holds whose
  execution has reached a terminal state, not holds that are merely old — a
  long execution legitimately holds one for its whole run, and releasing on age
  would return live holds under exactly the load that made them slow. The
  consequence is that a reservation whose execution row is *also* lost would
  not be swept. Nothing in this codebase deletes executions, so this is
  currently unreachable rather than handled.
- **Reservations do not span periods.** An execution that starts at 23:59:59
  holds against one day and reconciles against the same key. Correct for the
  ledger; means a long-running execution's spend is attributed to when it
  started rather than when it finished.
- **Currency is recorded but not converted.** A budget in EUR and an execution
  priced in USD would be compared numerically. Every price in this codebase is
  currently USD, so this is latent rather than live — but it is latent, not
  absent.

## Revisit when

- **A tenant's cost aggregation exceeds a budget an operator will accept.**
  Summing a tenant's spend is O(rows the tenant owns) and no index changes
  that; measured at 20ms for 109,398 rows in one tenant. The fix would be a
  materialized rollup, which is a second cost source and needs its own ADR
  overturning the no-parallel-store rule here — with numbers, the way Phase 4.2
  earned its index.
- **Multi-currency pricing appears.** The residual risk above becomes live the
  day a non-USD price is written, and the comparison in
  `ReservationService.reserve` must gain a conversion or a refusal.
- **Chargeback is built.** This phase does showback only. Billing someone
  raises questions this ADR does not answer, starting with whether an overshoot
  is charged to the tenant that caused it.
- **The overshoot bound proves too loose in practice.** The lever is
  `reservation_estimate` per budget, then Phase 4.3's `min_remaining_cost`. If
  neither suffices, the next option is a per-iteration reservation rather than
  a per-execution one — much more locking, and it should not be adopted without
  evidence that the cheaper levers failed.
