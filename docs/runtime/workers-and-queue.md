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

## Locking & heartbeats (§32)

Claiming a row also inserts an `execution_locks` row (`execution_id`
unique, `worker_id`, `acquired_at`, `expires_at` 5 minutes out,
`heartbeat_at`) and an `execution_attempts` row for this attempt. The lock
is deleted in a `finally` block after the attempt completes — success or
failure — so a crash mid-attempt would otherwise leave a stale lock past
its `expires_at`; a real out-of-process poller would additionally sweep
expired locks before claiming (not needed here since the worker runs
in-process, synchronously, and can't crash independently of the request
that invoked it).

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
