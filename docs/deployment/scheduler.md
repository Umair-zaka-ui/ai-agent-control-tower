# The distributed scheduler

Phase 3.8 (ACT-SRS-M3 §Phase-3.8, §9, §16, §20). Multiple scheduler instances
run concurrently and coordinate entirely through PostgreSQL, so a due job runs
exactly once, a crashed instance's work is recovered, and business logic stays
out of the scheduler.

---

## Why Postgres and nothing else

`SELECT ... FOR UPDATE SKIP LOCKED`. No Redis, no Celery, no Kafka — the same
mechanism `ExecutionWorkerService.claim_next` already uses for the execution
queue, and the same [ADR-0002](../architecture/adr/0002-postgresql-as-sole-datastore.md)
single-datastore commitment the rest of the platform is built on. A test
asserts no broker vocabulary appears in the scheduler.

The tradeoff is honest: this scales to the throughput one Postgres can serve,
which for *scheduled* work — sweeps every few minutes, not events every
millisecond — is not the binding constraint. If it ever becomes one, the
constraint will be visible as lock contention on `job_definitions`, not as a
mystery.

---

## The transaction boundaries — the whole phase in one section

There are exactly three transactions per run, and the boundary between the
first and second is the single most important line in the module.

| # | Transaction | What it does |
|---|---|---|
| 1 | **The claim** | `FOR UPDATE SKIP LOCKED` a due definition → insert the run row → advance `next_run_at` → **COMMIT** |
| 2 | **The handler** | Runs afterwards, holding *no* lock from step 1 |
| 3 | **Completion** | Records the outcome, commits |

### Why the claim must commit before the handler runs

This codebase has already paid to learn this once.
`ToolLoopOrchestrator._execute_parallel` documents the incident in full: a
claiming transaction held `FOR UPDATE` on an `agent_executions` row while
worker threads, on their own connections, tried to `INSERT` rows referencing
it. The foreign-key check needed `FOR KEY SHARE` on the locked row and blocked;
the main thread was simultaneously blocked joining those workers.
**Postgres's deadlock detector could not see it** — from the database's side
the main connection looked merely idle — so it hung instead of aborting.

The scheduler has the identical shape: a claim that locks a row, then a handler
that touches the database, possibly on other connections, possibly for minutes.
If the claim's transaction were still open, a handler blocking on anything the
claim holds would hang the instance — and every other instance would queue
behind the same definition row.

Committing first costs nothing. The lock's one job — stop a second instance
claiming the same occurrence — is complete the moment the run row is inserted,
and the unique index enforces it permanently rather than for the life of a
transaction.

This is proven three ways, not asserted once:

- **From inside a handler** (`test.asserts_no_open_transaction`): while the
  handler runs, a different connection takes `FOR UPDATE NOWAIT` on the
  definition row and succeeds. That is only possible if the claim already
  committed.
- **Behaviourally**: instance A mid-handler on job 1 does not block instance B
  claiming job 2.
- **Structurally**: `claim_due`'s body contains its commit and never calls
  `dispatch`.

---

## Exactly-once, and its honest limit

One `job_runs` row exists per `(definition, occurrence)`, enforced by
`uq_job_runs_occurrence`. Two instances computing the same due occurrence
cannot both create one — the second INSERT loses to the unique index. **The
database decides the race, not application timing**, the same primitive Phase
3.4 used for `uq_traffic_allocations_current` and 3.7 for
`uq_rollback_events_dedup`.

A **retry** and a **stale-lease recovery** both *reuse that row* rather than
inserting another. That is what makes "no duplicate successful run of the same
occurrence" a schema property rather than a detection problem: one row, one
attempt counter, exactly one terminal state.

**What it does not mean is exactly-once side effects.** If an instance dies
after its handler committed real work but before the run row was marked
`SUCCEEDED`, recovery will run that handler again. Every registered handler is
therefore an idempotent reconciliation — sweep current state, evaluate current
gates — never an event emitter, and the two deployment handlers additionally
inherit Phase 3.1's idempotency contract from the operations they call. This
is stated rather than hidden because it is the honest limit of what a database
lease can promise.

### The occurrence key

Derived from the instant a job was **due**, not the instant it was claimed:

```
INTERVAL   →  i:2026-08-17T19:05:00+00:00
ONE_TIME   →  once
```

A key based on claim time would differ per instance and defeat the guard
entirely. A one-time job's constant key also means a re-enabled one-time job
cannot silently fire twice.

---

## The §20 proof

**Part 1 — two instances, one job, one run.** Two schedulers on *real separate
connections* see the same due job. The first holds the definition lock; the
second, using `SKIP LOCKED`, finds nothing rather than blocking. Exactly one
run row exists and the handler ran exactly once. Deterministic by construction —
instance A's transaction is held open across B's attempt, so nothing depends on
thread scheduling.

**Part 2 — crash and recovery.** Instance A claims a job then "crashes": the
lease is never renewed and the run never completes. Once the lease expires,
instance B reclaims **the same run row**, runs it, and completes it.
`recovered_from` records where it came from. Still one row for the occurrence,
so a duplicate successful run is not merely absent but impossible.

Neither test uses an in-process mutex or a thread barrier. The property is that
two *processes* sharing only a database cannot both run one job; a test sharing
a session would prove nothing about that.

---

## Leases

| Field | Meaning |
|---|---|
| `lease_owner` | instance id (`host:pid` — tells an operator which process to inspect) |
| `lease_expires_at` | when a peer may reclaim |
| `heartbeat_at` | last renewal by the owner |

A lease deliberately **outlives its job's timeout** (`timeout + 60s`). If they
were equal, a handler finishing exactly at its deadline would race its own
reclamation and two instances could briefly both believe they owned the run.
The margin keeps the two failures distinct: the *timeout* stops a slow handler,
the *lease* detects a dead one.

A heartbeat from a **dispossessed** owner is ignored. An instance that stalled
long enough to be reclaimed must not be able to resurrect its ownership — two
owners is the one thing the lease exists to prevent.

An **exhausted** run is `ABANDONED` rather than retried forever, so a job that
kills its process every attempt cannot become an infinite reclaim loop across
the fleet.

**Retry and crash recovery share one mechanism.** A failed attempt with budget
remaining is re-armed by putting its lease *in the past* by the backoff amount,
so the ordinary stale-lease path picks it up. Two code paths that could
disagree about attempt counting would be two chances to get exactly-once wrong.

---

## Handlers — the scheduler dispatches, it does not decide

Business logic lives in the domain that already owned it. These handlers are
thin adapters:

| `handler_key` | Calls | Owner |
|---|---|---|
| `integration.connector_health_sweep` | `run_sweep_once()` | 2.1.3 |
| `deployment.canary_auto_advance` | `evaluate_and_advance()` | 3.5 |
| `deployment.rollback_trigger_evaluation` | `RollbackService.evaluate()` | 3.7 |
| `platform.expired_state_cleanup` | expired locks + idempotency-key TTL | 3.8 |

Both deployment methods were written to be driven on a timer — 3.5's docstring
says *"Interim until Phase 3.8: its scheduler will call exactly this method on
a timer, with no change required here."* No change was required there.

Tests assert the separation mechanically: no threshold, gate or weight
vocabulary appears in either the scheduler or the handlers.

**Dispatch is a fixed dictionary, not dynamic import.** A `handler_key` is
looked up in a module-level registry populated by decorator at import time; an
unrecognized key raises `JOB_HANDLER_UNKNOWN`. No import path or dotted name
ever comes from the database, so a row — however it got written — can never
make the scheduler execute arbitrary code. An AST test asserts `import_module`,
`__import__`, `eval`, `exec` and `getattr` appear nowhere in dispatch.

---

## The scheduler principal

3.5's and 3.7's bounded operations take an `actor: User` and scope Phase 3.1's
idempotency contract by `actor.organization_id`. A scheduler has no human, so
it uses **one non-human `users` row per organization**, created on demand.

It **cannot authenticate**: `password_hash` is a value no hashing scheme here
can produce, and `is_active` is false. A test attempts login with several
candidate passwords and asserts every one is rejected. It exists to be an
*attributable* principal, never a usable login.

Two alternatives were considered and rejected:

- *Reusing the org owner* would make the audit trail claim a real person
  triggered every scheduled canary advance and rollback. Phase 3.7 deliberately
  writes `initiated_by = NULL` for automatic rollbacks for exactly this reason;
  borrowing a human's identity would undo that on the very path 3.7 protects.
- *Widening the bounded operations to accept `actor=None`* is arguably cleaner
  semantics but modifies `canary.py`, which 3.6 and 3.7 both pin byte-identical
  to `main` by test.

---

## The interim scheduler is retired

Phase 2.1.3's `app/integration/scheduler.py` specified its own retirement:
*"delete this module, delete its one call site in `app/main.py`'s lifespan,
register the same iteration as a real job. Nothing here is designed to be
extended in place into that system."*

That is exactly what happened. The sweep logic moved to
`app/integration/sweep.py` **unchanged**; the `asyncio` task, `start`/`stop`
pair and lifespan hook are gone. No parallel scheduling path remains, and a
test asserts the module no longer exists.

`CONNECTOR_HEALTH_SCHEDULER_ENABLED` survives with a real continuing meaning:
it now decides whether the seeded job definition is created **enabled** rather
than whether an in-process task starts. Default remains `false` — retiring an
opt-in mechanism must not quietly turn it on.

**The API process deliberately does not start a scheduler.** One running inside
the web process would scale with HTTP traffic rather than scheduling need, and
every API replica would silently become a competing instance.

Phase 2.1.3's `test_ac20` was updated rather than deleted: its source
assertions described a file that no longer exists, but the behaviour it
protected (a sweep really visits active instances and records a `SCHEDULED`
check) is asserted verbatim. It is now *stricter* — it also asserts the
retirement actually happened.

---

## Running it

```bash
# One instance
python -m app.scheduler.runner

# Seed the platform-level job definitions (disabled by default)
python -m app.scheduler.runner --seed-platform-jobs

# A fleet: just start more. No leader election, no peer list.
python -m app.scheduler.runner &
python -m app.scheduler.runner &
```

Instances discover work by competing for it, and `SKIP LOCKED` makes losing
free. Adding an instance is starting another process.

Each tick does **at most one unit of work** — recover one stale run, else claim
one due job, else nothing — then sleeps. Deliberately unambitious: a tick that
drained the whole queue would pin one instance to a long backlog while its
peers idled, and the fleet drains faster when each instance takes one item and
comes back.

`--max-ticks` bounds the loop so tests drive it deterministically instead of
racing a sleep. `SIGINT`/`SIGTERM` stop *after* the current tick.

---

## Recovery (§16)

| State | Kind | Behaviour |
|---|---|---|
| `job_definitions` | durable | restored with the database |
| `job_runs` history | durable | restored with the database |
| **leases** | **ephemeral** | never preserved — a stale lease is recovered, not honoured |

After a crash or a restore, a lease is evidence of an owner that *was*, never
one that *is*. No job is permanently lost by a crash: worst case its occurrence
is retried by whichever instance notices first, and the schedule still advances.

Missed INTERVAL occurrences are **skipped, not queued**. A fleet down for an
hour resumes sweeping; it does not run twelve catch-up sweeps back to back. The
sweeps are idempotent reconciliations, not events with individual meaning, and a
thundering herd of them is exactly what an already-struggling system does not
need.

---

## API

| Method | Path | Permission |
|---|---|---|
| `GET`/`POST` | `/api/v1/runtime/scheduler/jobs` | `.view` / `.manage` |
| `GET`/`PATCH` | `.../jobs/{id}` | `.view` / `.manage` |
| `GET` | `.../jobs/{id}/runs` | `runtime.scheduler.view` |
| `GET` | `.../handlers` | `runtime.scheduler.view` |

**No route can dispatch a job.** That is a safety property: an HTTP-triggered
run would bypass the lease entirely — no occurrence row, no ownership, no
protection against a peer running it simultaneously. Every path to execution
goes through a scheduler instance, which is the only place the exactly-once
guarantee holds.

Platform-level jobs are **visible** to tenants (a tenant debugging stale
connector health should be able to see whether the sweep is even on) but not
**editable** by them: they run outside every tenant boundary, so no tenant
administrator is the right authority to disable them.

### Error codes

| Code | HTTP | Meaning |
|---|---|---|
| `JOB_DEFINITION_NOT_FOUND` | 404 | unknown or cross-tenant |
| `JOB_HANDLER_UNKNOWN` | 422 | not in the registry — well-formed, but names something unimplemented |

---

## Deliberately not here

| Excluded | Owning phase |
|---|---|
| The distributed execution worker fleet | 3.9 — reuses this lease discipline |
| Operator frontend | 3.10 |
| CRON schedules | not justified yet; `schedule_kind` widens additively when a real calendar requirement appears |
| Any new deployment/rollout/rollback logic | 3.1–3.7 own it; the scheduler drives their bounded operations |
| Redis / Celery / Kafka | forbidden — Postgres is the mechanism |
