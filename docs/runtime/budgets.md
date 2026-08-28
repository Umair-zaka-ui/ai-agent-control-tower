# Budgets — scopes, modes, and reserve-then-reconcile

> **Phase 4.4 (ACT-SRS-M4 §4.4, §11, §35).** How a spending ceiling is defined,
> how it is enforced without two workers spending the same dollar, and how it
> reaches enforcement without becoming a second enforcement path. The reasoning
> is [ADR-0010](../architecture/adr/0010-budget-reservation-semantics.md); the
> cost figures budgets are measured against are in
> [cost-governance.md](./cost-governance.md).

## The one-paragraph version

A budget is a **limit** plus a **mode**. Only two of the four modes enforce
anything. An enforcing budget takes an **atomic reservation** before an
execution runs — so the next worker sees that money already gone — and
**reconciles** it to real cost afterwards, returning whatever was over-held. A
budget with no headroom does not stop an execution; it reports zero remaining,
and Phase 4.3's governance engine turns that into a `STOP`. There is still
exactly one thing on this platform that can stop an execution.

## Modes

| Mode | Reserves? | Reaches the engine? | What it does |
|---|---|---|---|
| `INFORMATIONAL` | No | No | Records a threshold crossing |
| `WARNING` | No | No | Records a threshold crossing, at WARNING severity |
| `HARD_LIMIT` | **Yes** | **Yes** | Exhausted ⇒ engine returns `STOP` / `BUDGET_EXCEEDED` |
| `APPROVAL_REQUIRED` | **Yes** | **Yes** | Past threshold ⇒ engine returns `CHALLENGE` |

**The first two cannot block, and not because a branch says so.** They take no
reservation and never populate a checkpoint context, so there is no code path
from them to the engine at all. That is FR-032 enforced by construction.

Modes exist because an organization's first budget is almost never a hard
limit — it is someone watching a number for a month to see whether the platform
agrees with their finance team. A system whose only setting is "stop
production" is a system nobody switches on. Phase 3.7's rollback triggers have
a `NOTIFY_ONLY` mode for the same reason, and Phase 4.3's governance policies
have their `mandatory` flag.

## Scopes and periods

Scopes: `ORGANIZATION`, `PROJECT`, `AGENT`, `ENVIRONMENT`, `MODEL`. Periods:
`DAILY`, `MONTHLY`, `EXECUTION`.

Resolution returns **every applicable budget**, most specific first — not a
single winner. Picking one would let a narrow per-agent allowance silently
switch off the organization-wide ceiling above it. An execution must satisfy
all of them; the most specific is merely evaluated first, so its message is the
one an operator sees when several would object. Same rule as Phase 4.3's policy
resolution and Phase 3.7's rollback triggers.

An `EXECUTION` period makes each execution its own bucket, so a per-execution
ceiling is expressed by the same summation as a daily or monthly one rather
than by a second code path.

A scope that names nothing is **refused at write time** — an `AGENT` budget
with no `scope_id` would govern no execution while looking configured, which is
the failure Phase 4.3 refused for a misspelled constraint key.

## Reserve-then-reconcile

### The failure it prevents

Twenty workers each read *"$9 remaining"* against a $10 budget, each conclude
they may spend $9, and $180 is spent. Every worker read a true balance and
acted on it correctly. The defect is the gap between the read and the act — and
that gap contains a model call.

### The mechanism

One transaction:

1. `SELECT ... FROM budgets WHERE id = :id FOR UPDATE` — every concurrent
   claimant queues **in the database**, across processes and machines. §11
   forbids an in-process lock explicitly, and the Phase 3.9 worker fleet would
   make one worthless anyway.
2. Sum `RESERVED` holds + `RECONCILED` actuals for this period — an index read
   on `ix_budget_reservations_period`.
3. Refuse if the estimate would not fit. Otherwise insert the reservation.
4. **Commit**, releasing the lock. Nothing below this point holds it.

The lock covers two indexed statements and is never held across model or tool
I/O — the commit-before-dispatch rule applied to money.

Afterwards, the hold is **reconciled**: `actual_amount` is set and the status
becomes `RECONCILED`, which counts the actual instead of the estimate. Over-
reservation is returned by that status change alone — there is no separate
release step, and therefore no separate step that can be skipped.

### What is guaranteed, and what is not

This is the most important paragraph on this page.

> **Guaranteed:** the sum of *reserved* amounts never exceeds the limit. Two
> workers cannot both consume the same remaining allowance.
>
> **Not guaranteed:** that *actual* spend never exceeds the limit. A model
> call's cost is unknowable until it returns, so an execution admitted with a
> $0.25 hold that costs $0.40 overshoots by $0.15. The total overshoot is
> bounded by the sum of (actual − reserved) over executions in flight.

Claiming the second would require knowing a price before paying it. There is a
test that asserts the overshoot is real, so nobody discovers it in production
instead of here.

Per execution, the overshoot is separately bounded by Phase 4.3's
`min_remaining_cost` headroom rule, which stops a loop before dispatching an
iteration the remaining budget could not absorb.

### The estimate

`reservation_estimate` on the budget, falling back to
`settings.BUDGET_DEFAULT_RESERVATION` (0.05). It is a real trade-off in both
directions: hold too much and a tight budget admits fewer concurrent executions
than it could afford; hold too little and more executions are in flight than
the balance can cover if they all overrun. There is no correct default, only a
small one — a default that guessed high would make every unconfigured budget
behave as if it were much smaller than its owner wrote down.

### Idempotency

A partial unique index on `(budget_id, execution_id) WHERE status <> 'RELEASED'`
means one execution holds at most one live reservation against one budget.
Postgres refuses the second insert; the application does not have to remember
not to try. A `RELEASED` row does not participate, so a retried attempt claims
afresh — which is what makes an execution's second attempt behave like its
first, and is why orphan release is a correctness requirement rather than
housekeeping.

### Orphans

Every terminal path settles its own reservation: success reconciles, failure
reconciles to whatever the transcript recorded, cancellation releases. The
sweeper is the net beneath them, for a process killed between the reservation
commit and the terminal write.

It is **not time-based**, deliberately. A reservation is not orphaned because
it is old — a long execution legitimately holds one for its whole run. It is
orphaned because *the execution it belongs to has finished and it was not
reconciled*. Releasing on age would return live holds under exactly the load
that made them slow.

A leaked reservation would permanently shrink a tenant's budget every time a
worker died, turning an availability incident into a financial one.

## Two accounting sources

Enforcing budgets are accounted from the **reservation ledger**. Signalling
budgets are accounted from **real spend on `agent_executions`**.

The split is deliberate, not an oversight. You cannot atomically claim a share
of a number you compute by scanning a table, so enforcement needs a ledger.
Signalling budgets take no reservations, so their ledger is empty and would
report 0% forever — they read the authoritative cost directly instead.

**The consequence, stated because someone will meet it:** a budget switched
from `WARNING` to `HARD_LIMIT` starts its ledger at that moment, so its
reported utilization drops to what has been reserved since. That is defensible
— a budget governs from when it began governing — but it is surprising, and it
is written down here rather than left to be discovered.

## The enforcement seam

```
app/finops  ──reports a number──▶  RuntimeGovernanceEngine  ──▶  ALLOW/DENY/CHALLENGE/STOP
 (reserve, measure,                 (Phase 4.3: the one place
  reconcile, release)                that decides)
```

A refused reservation is **not** a refused execution. It is a budget with no
headroom, reported as `budget_remaining <= 0`, which the engine's budget
constraint tier turns into a `STOP` at `BEFORE_FIRST_MODEL_CALL` — before any
model call is made.

`app/finops` contains no code that writes an execution's status, raises the
governance stop, or calls the kill switch, asserted over the AST. The budget
constraint was added as a **separate tier** in the engine rather than as
another built-in cap, specifically so that Phase 4.3's exact cap-ordering test
did not have to be weakened to make room for it.

A budget-driven decision records `budget_id` on the governance decision row and
leaves `policy_id` null — a decision carries at most one of the two, and the
lineage names whichever ceiling decided.

## API

| Method | Path | Permission |
|---|---|---|
| GET/POST | `/api/v1/budgets` | `runtime.budget.view` / `runtime.budget.manage` |
| GET/PATCH/DELETE | `/api/v1/budgets/{id}` | view / manage |
| GET | `/api/v1/budgets/{id}/utilization` | `runtime.budget.view` |

Writes accept `Idempotency-Key` (Phase 3.1's contract): a retried create must
not leave two ceilings where the operator asked for one, because both would
evaluate and the tighter would fire with no obvious explanation.

`DELETE` **disables** rather than deletes. A budget's reservations are the
record of money actually spent under it, and a cascade would erase that.

Two new permissions, not three: the cost read model reuses the pre-existing
`runtime.cost.view`. Budgets get their own codes because reading a spend figure
and configuring a ceiling that can halt production are different powers.

## Errors

| Code | HTTP | Meaning |
|---|---|---|
| `BUDGET_NOT_FOUND` | 404 | Also returned for another tenant's budget (§34) |
| `BUDGET_INVALID` | 422 | A scope, mode, period or amount the engine cannot use |
| `BUDGET_EXCEEDED` | 402 | Reached an execution **only** through a 4.3 decision |
| `BUDGET_RESERVATION_CONFLICT` | 409 | The idempotency index refusing a second live hold |

`BUDGET_EXCEEDED` is **non-retryable**: an exhausted budget is still exhausted
on the next attempt, and each retry would take and release another hold against
a budget with nothing left.

`402 Payment Required` rather than `403`: the request was permitted, the money
was not there.

## See also

- [cost-governance.md](./cost-governance.md) — where the numbers come from
- [ADR-0010](../architecture/adr/0010-budget-reservation-semantics.md) — why
  reservations, and what the guarantee is
- [runtime-governance.md](./runtime-governance.md) — the engine that enforces
- [runtime-policy-checkpoints.md](./runtime-policy-checkpoints.md) — where the
  budget constraint is evaluated
