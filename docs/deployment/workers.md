# The execution worker fleet (Phase 3.9)

Agent executions run on independently-operable worker processes. This document
covers what a worker is, how it claims work, the transaction boundary that
makes the fleet safe, how it drains and recovers, and the honest limits of the
guarantees.

## Running one

```bash
python -m app.workers.runner
python -m app.workers.runner --concurrency 4 --cohort 01-canary
python -m app.workers.runner --max-ticks 1        # one poll, then exit
```

Run as many as you like, on as many machines as you like. They coordinate
through PostgreSQL and nothing else — no broker, no leader election, no
membership protocol. SRS §Phase-3.9 forbids adding Redis/Celery/Kafka, and
nothing here wanted them: `SELECT ... FOR UPDATE SKIP LOCKED` is a queue.

**The API process deliberately starts no worker.** An execution worker calls
model providers and spends real money, so starting one must be an explicit act
of deployment rather than a side effect of serving HTTP. Phase 3.8 made the
same decision for the scheduler.

| Setting | Default | What it controls |
|---|---|---|
| `WORKER_CONCURRENCY` | `1` | Executions one process runs at once |
| `WORKER_COHORT` | `default` | The rolling unit this process joins |
| `WORKER_POLL_INTERVAL_SECONDS` | `2.0` | Time between polls |
| `WORKER_STALE_AFTER_SECONDS` | `90.0` | Silence after which a process is presumed dead |

`WORKER_CONCURRENCY` defaults to 1 rather than to a core count on purpose. An
execution is bounded by model and tool network latency, not by CPU, so the
right number depends on provider rate limits. A default that guessed high
would silently multiply every tenant's concurrent provider calls the first
time anyone started a worker.

## The claim, and the boundary that matters

```sql
SELECT * FROM agent_executions
WHERE status = 'QUEUED'
ORDER BY <priority CASE>, queued_at ASC
LIMIT 1
FOR UPDATE SKIP LOCKED
```

This is M1's claim query, unchanged. `SKIP LOCKED` is what makes contention
cheap: two workers racing never claim the same row — one wins, the other's
query skips the locked row and moves on.

Claiming also inserts an `execution_locks` row (`execution_id` **UNIQUE**) and
an `execution_attempts` row. That unique constraint is the structural
guarantee that no two workers successfully execute one claimed execution. It
is not a convention the workers politely observe; the database refuses.

### Commit-before-dispatch

**`claim_next` commits before returning.** This is the single most important
line in Phase 3.9.

Until 3.9 it *flushed*. The `FOR UPDATE` lock was therefore held for the whole
attempt — every model call, every tool call, every byte of network I/O — and
released only when `run_once`'s `finally` committed. That was survivable with
one inline caller. It is not survivable with a fleet, and the failure it
produces is one this codebase has already been bitten by:

> `ToolLoopOrchestrator._execute_parallel` had to commit `self.db` by hand
> before spawning tool threads. A fresh session inserting a `tool_calls` row
> needs `FOR KEY SHARE` on the parent `agent_executions` row, which the
> still-held `FOR UPDATE` blocks — while the main thread sits in
> `future.result()` waiting for that same tool thread. A thread-join waiting
> on a database lock wait is a real deadlock that Postgres's detector cannot
> see, because from its side the main connection looks idle.

Committing at the claim dissolves that class of bug at the source rather than
working around it one call site at a time. It is safe because the lock has
already done its one job: the row is no longer `QUEUED`, and the *committed*
status change is what excludes peers now — permanently, rather than for the
duration of a transaction.

Three transactions per attempt:

| # | Boundary | Contents |
|---|---|---|
| 1 | `claim_next` | status → RUNNING, lock row, attempt row — **committed** |
| 2 | the attempt | model → tool → model, results written |
| 3 | `run_once` `finally` | lock deleted, terminal state committed |

**What is and is not claimed.** No lock is held across model or tool network
I/O — that is proven, from inside a running model call, in
`test_ac03_no_lock_is_held_across_model_io`. Later in the attempt the worker
does write results to its own row, and those UPDATEs hold a row lock until
transaction 3 commits. That is normal and harmless: the row belongs to this
worker, no peer can claim it, and no tool thread runs after that point.

### One behavioural change, stated plainly

A worker that dies mid-attempt used to have its claim rolled back by the
database, returning the execution to `QUEUED` instantly. Now the claim is
committed, so the execution stays `RUNNING` until its lease expires and
`reap_expired_locks` applies the retry policy. Recovery is therefore slower by
at most one lease — and in exchange it is *observable*: there is a durable
record of who held what and for how long, which is the difference between a
fleet you can operate and one you can only guess about.

## Lifecycle, drain and graceful shutdown

| Status | Meaning |
|---|---|
| `RUNNING` | Claiming and executing |
| `DRAINING` | **Claim nothing new, finish what you hold** |
| `STOPPED` | Gone |

`DRAINING` is a precise contract rather than "stopping soon", which is why
graceful shutdown needs no separate flag: shutdown is drain plus waiting, and
the two can never disagree.

```
POST /api/v1/runtime/fleet/workers/{worker_id}/drain
```

This writes the *request*. `ExecutionWorker.refresh()` is what turns it into
behaviour — the worker reconciles on its next poll, within one interval.
Reconciliation is deliberately one-directional: a worker will pick up a
DRAINING or STOPPED instruction, but will never promote itself back to
RUNNING, because undoing an operator's drain from inside the process being
drained is never the right resolution of that disagreement.

A restarted worker re-registers under the same `worker_id` (UNIQUE), updating
its row rather than accumulating one per launch, and comes back RUNNING — a
process that has just started is by definition not draining.

## Recovery: what is durable, what is not

Per RECOVERY.md's durable/ephemeral split:

| | Durable | Ephemeral |
|---|---|---|
| `agent_executions` | ✅ the work itself | |
| `execution_attempts` | ✅ history | |
| `execution_locks` | | ⚠️ a lease; expires |
| `worker_registrations` | | ⚠️ describes a live OS process |

After a restart or a restore, a `worker_registrations` row describes a process
that no longer exists. Nothing of value is lost: workers rebuild the table by
re-registering within one poll interval. What must survive is the *executions*
those workers were running, and those are fully durable.

**Two clocks, deliberately separate.** A worker goes stale after
`WORKER_STALE_AFTER_SECONDS` of silence; its executions' locks expire on their
own `expires_at`. Whichever fires first, the outcome is the same, and neither
can leave an execution owned by a process that is gone.

**Worker recovery does not release executions.** `WorkerFleetService.reap_stale_workers`
marks the *worker* dead and audits the affected tenants; M1's
`ExecutionWorkerService.reap_expired_locks` owns execution recovery — it
applies the real retry policy, writes the attempt record and emits the
terminal audit. Two components implementing that policy could disagree about
whether an execution had attempts left, and that disagreement is how an
execution gets run twice or dropped entirely.

Every worker sweeps on every tick rather than a designated leader doing it. A
leader needs an election, and an election needs exactly the distributed
coordination this platform deliberately does not have. Concurrent sweeping is
harmless: the operations are idempotent reconciliations.

For the case with no live member at all — the fleet is entirely down —
`POST /api/v1/runtime/fleet/reap` runs the sweep on demand.

## The honest limit on exactly-once

What the fleet guarantees is exactly-once **dispatch**, not exactly-once side
effects. A worker that dies after its execution has called a tool but before
the result is committed will have that execution recovered and retried, and
the tool will have been called twice.

M1 already faced this and answered it where the answer belongs —
`ToolGatewayService` knows which tools are idempotent, and the retry policy
never retries a policy denial. Phase 3.9 does not weaken that answer, and it
cannot promise more than the layer beneath it delivers. This is the same limit
Phase 3.8 stated for the scheduler, for the same reason.

## Backpressure and observability

```
GET /api/v1/runtime/fleet              # workers + live capacity per cohort
GET /api/v1/runtime/fleet/queue-depth  # what the fleet is facing
```

`queue-depth` reads `queued`/`running` from `agent_executions` rather than
summing worker rows, because a worker row can lag by up to one heartbeat and a
queue-depth number that lags is exactly the number an autoscaler must not act
on.

A worker at capacity refuses to claim before issuing any query
(`_acquire_slot`), so backpressure costs nothing at the database.

### Why these live at `/fleet` and not `/workers`

`GET /api/v1/runtime/workers` and `POST .../workers/reap` have existed since
M1: the first reports worker *activity* derived from execution attempts, the
second reaps expired execution locks. Both are still correct and still used.
This phase manages a different thing — registered worker *processes* and their
declared capacity — so it nests beside them rather than taking their paths
over, exactly as Phase 3.7 nested under `/deployments/{id}/rollback/...`
rather than seizing the Phase 5.0 `/rollback` endpoint.

### What the fleet API cannot do

**No route can run an execution**, and none can create a registration.

If HTTP could dispatch, an authenticated caller could run agent work with no
lease and no worker identity — defeating `execution_locks`' unique constraint
by simply never taking one. If HTTP could register, a caller could inject
phantom capacity into the fleet, and rolling derives *real step weights* from
that capacity, so phantom workers would move production traffic onto machines
that do not exist.

## Cohorts

A cohort is a declared label (`--cohort`). Workers sharing one are one cohort;
its capacity is the summed declared concurrency of its live, heartbeating
members. Cohorts exist for rolling deployment — see
[strategies.md](strategies.md#rolling).

Name them in the order you want them converted (`01-canary`, `02-rest`):
rolling converts cohorts in name order, which is the one ordering an operator
can predict and control.
