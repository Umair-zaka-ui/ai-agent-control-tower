# The queue & worker runtime

## The queue is `agent_executions` (§30)

No Redis/Celery/RabbitMQ dependency was added to this environment — §30
explicitly allows a "PostgreSQL-backed queue for development," and that's
what this is. A worker claims work with:

```sql
SELECT * FROM agent_executions
WHERE status = 'QUEUED'
ORDER BY <priority CASE>, queued_at ASC
LIMIT 1
FOR UPDATE SKIP LOCKED
```

(`ExecutionWorkerService.claim_next`, using SQLAlchemy's
`with_for_update(skip_locked=True)`). `SKIP LOCKED` is what makes this safe
under concurrency: two workers racing this query never claim the same row —
one gets it, the other's query simply skips the locked row and finds the
next one (or nothing). A composite index
`(status, priority, queued_at)` (migration `0023_agent_runtime`) keeps the
claim query an index scan rather than a sequential scan as the table grows.

Priority ordering (`CRITICAL, HIGH, NORMAL, LOW`) is a SQL `CASE` expression
compiled once at import time (`_PRIORITY_RANK` in `services.py`), not
recomputed per call.

The claim query is **intentionally global** — it is not filtered by
organization or agent. A real worker pool serves every tenant fairly, by
queue position, not by tenant; the oldest `QUEUED` row anywhere gets
claimed first. One consequence worth knowing when testing against this
queue directly: if an unrelated `QUEUED` row is left behind (a crashed
test, a manually-inserted row), it — not the row you just enqueued — is
what the next `run_once()` call claims, because it's older. Production
code never notices this (nothing is ever left `QUEUED` without a worker
eventually claiming it); it only matters if you're constructing rows by
hand.

## Locking & heartbeats (§32)

Claiming a row also inserts an `execution_locks` row (`execution_id`
unique, `worker_id`, `acquired_at`, `expires_at` 5 minutes out,
`heartbeat_at`) and an `execution_attempts` row for this attempt. The lock
is deleted in a `finally` block after the attempt completes — success or
failure.

If a worker crashes mid-attempt (or is killed, or loses its network
connection) without reaching that `finally`, the execution is stuck
`RUNNING` and the lock's `expires_at` is never renewed.
`ExecutionWorkerService.reap_expired_locks()` recovers this: it finds
every `execution_locks` row past its `expires_at`, runs the *same*
fail-or-retry policy below against the execution it was guarding
(`WORKER_UNAVAILABLE` — requeue if attempts remain, else
`DEAD_LETTERED`), and drops the stale lock. `claim_next()` calls it
opportunistically before every claim, so recovery happens automatically
the next time *any* worker asks for work — no separate sweeper process is
needed in this environment. `POST /runtime/workers/reap` also exposes it
directly, for operator-triggered recovery and to see how many were
actually stuck (`{"reaped": N}`).

## Execution timeout (§36)

`deployment.runtime_limits.maximum_execution_seconds` (default 300s)
bounds the model invocation: `ExecutionWorkerService._execute` runs
`ModelGatewayService.invoke` in a one-worker `ThreadPoolExecutor` and calls
`future.result(timeout=...)`. On timeout, the future is abandoned (not
killed — Python has no safe way to kill a running thread) and
`pool.shutdown(wait=False)` so the abandoned call doesn't itself block the
worker; the attempt fails with `EXECUTION_TIMED_OUT`, which follows the
normal retry policy below but reports as `TIMED_OUT` rather than
`DEAD_LETTERED` once attempts are exhausted, so the terminal reason stays
distinguishable in the UI.

Only the model call is time-boxed. Tool calls (`ToolGatewayService.invoke`,
below) are not run on that same thread — they write through the worker's
own `self.db`, and a SQLAlchemy `Session` is not safe to use from two
threads at once. Since an abandoned future keeps running in the
background rather than actually stopping, giving it DB access would let it
race the thread that gave up waiting on it. In practice this doesn't limit
real coverage: the only outbound-I/O boundary in this build is the model
call (§43 — tool calls are in-process only, no outbound network/DB access
is wired up), which is exactly the boundary that's timed.

## How this environment actually runs the worker

There is no standalone worker process. `ExecutionRequestService` calls
`ExecutionWorkerService(db).run_once()` **inline, synchronously, right
after** enqueueing — the same trick `CELERY_TASK_ALWAYS_EAGER=True` plays
for local Celery development. This is why an execution created through the
UI shows `SUCCEEDED` (or `FAILED`) within the same request/response cycle
rather than sitting `QUEUED` until a poller wakes up.

`ExecutionWorkerService` itself has no idea it's being called this way —
`run_once(worker_id)` claims exactly one row and processes it, full stop.
Pointing a real out-of-process poller (a loop calling `run_once` on a
timer, in a separate process or container) at the same database would work
identically and is the natural next step for a production deployment; only
`ExecutionRequestService`'s post-enqueue call would need to be removed.

## Retry policy (§34) and dead-lettering (§35)

On failure, `_fail_or_retry` checks
`deployment.runtime_limits.maximum_retries` (default `3`, so 4 total
attempts) against `execution.attempt_count`:

- **Non-retryable error codes never retry**, regardless of attempts
  remaining: `RUNTIME_POLICY_DENIED`, `MODEL_NOT_APPROVED`,
  `TOOL_ACTION_NOT_ALLOWED`, `TOOL_NOT_ASSIGNED`, `TOOL_NOT_FOUND`,
  `VALIDATION_ERROR`, `MODEL_PROVIDER_UNAVAILABLE` — these are permanent
  conditions a retry cannot fix (an unassigned tool doesn't become assigned
  by trying again).
- **Everything else** goes back to `QUEUED` (with a fresh `queued_at`) if
  attempts remain, or `DEAD_LETTERED` once `maximum_retries` is exhausted.
- A cancelled execution (`cancel_requested`) is checked first and short-
  circuits straight to `CANCELLED` without attempting anything.

Every attempt — success, failure, or cancellation — gets its own
`execution_attempts` row (`GET /executions/{id}/attempts`), so the full
retry history is visible on the Execution Detail page.

## Tool calls inside an execution

If `input_payload.tool_calls` is a list of `{tool_name, action, params}`,
the worker invokes each through `ToolGatewayService` in order (see
[gateways.md](gateways.md)) and records a `tool_calls` row per call. A
tool-call failure raises the same way a model failure does, and is subject
to the same retry policy above.
