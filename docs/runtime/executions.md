# The Runtime Gateway & executions

`/runtime/executions` · `runtime.execution.*` permissions.

`ExecutionRequestService.request_execution` is the Runtime Gateway (§24) —
the only supported entry point for execution. `POST /api/v1/runtime/executions`
walks, in order:

```
Agent exists & ACTIVE (not SUSPENDED)
   │
Deployment resolved (explicit deployment_id, or the agent's active
   deployment) & ACTIVE
   │
Agent version resolved from the deployment, not REVOKED, PUBLISHED/DEPRECATED
   │
Input contract validated against the agent definition's input_schema
   (§7.2) — a mismatch raises VALIDATION_ERROR (422), no execution row created
   │
Idempotency check (§33) — same key + same payload hash returns the
   existing execution; same key + different payload → 409 IDEMPOTENCY_CONFLICT
   │
AuthorizationGateway.authorize(actor, "runtime.execution.create",
   resource_type="agent", resource_id=agent.id, ...)   ← RBAC/ABAC (§4.4)
   │  not allowed → execution row saved as DENIED, returned (not raised)
   │
RuntimePolicyService.evaluate(agent, version, deployment)   ← limits, approved
   │  models, environment restrictions (§38)
   │  not allowed → execution row saved as BLOCKED, returned
   │
requires_approval? → PENDING_APPROVAL + a runtime_approvals row
   │
QUEUED, queued_at=now, idempotency record stored
   │
ExecutionWorkerService.run_once() ← inline, eager (see workers-and-queue.md)
```

A denied or blocked request is **not** an HTTP error — the execution row is
created either way (status `DENIED`/`BLOCKED`), so every attempt is
auditable and inspectable from the Execution Detail page, matching the
SRS's own example responses (`{"execution_id", "status", "decision"}`).
Structural failures (unknown agent, unpublished version, idempotency
conflict) *do* raise — those are client errors, not policy outcomes.

## State machine (§27)

```
CREATED → AUTHORIZING → DENIED
                    │
                    ├─→ PENDING_APPROVAL → REJECTED
                    │                  └─→ QUEUED
                    ├─→ BLOCKED
                    └─→ QUEUED → RUNNING → SUCCEEDED
                                       ├─→ FAILED
                                       ├─→ QUEUED (retry)
                                       ├─→ TIMED_OUT
                                       ├─→ CANCELLED
                                       └─→ DEAD_LETTERED
```

Every transition is validated centrally by
`_set_execution_status`/`_EXECUTION_TRANSITIONS` in `services.py` (§27's
"every state transition must be authorized and audited" — here,
*validated*: an assignment not in the table raises
`INVALID_EXECUTION_TRANSITION` rather than silently landing the row in a
state the machine doesn't recognize) — every call site that used to write
`execution.status = "..."` directly now goes through it, so a bug that
tries to (for example) resurrect a `SUCCEEDED` execution back to `QUEUED`
fails loudly at the point of the mistake instead of corrupting the row.

`SCHEDULED` and `WAITING_FOR_*` are modeled in the status column
(free-form `String(24)`, not a DB enum) but not currently produced — this
environment's synchronous inline worker has no separate scheduling delay.
`TIMED_OUT` **is** produced: see
[workers-and-queue.md](workers-and-queue.md) for the timeout enforcement
and the retry/dead-letter mechanics that produce
`FAILED`/`TIMED_OUT`/`DEAD_LETTERED`.

## Idempotency (§33)

`idempotency_records` is keyed on `(organization_id, agent_id,
idempotency_key)`; `request_hash` is `sha256` of the sorted-key JSON of
`input_payload`. A replayed request with the same key returns the original
execution unchanged (no new row, no re-run); a reused key with a different
payload is rejected outright rather than silently running the new payload
under the old key. Records expire after 24h
(`IdempotencyService.store(..., ttl_hours=24)`).

## Cancellation, retry, replay

- **Cancel** (`POST /executions/{id}/cancel`) — a queued/pending/
  authorizing execution is cancelled immediately; anything already terminal
  raises `EXECUTION_ALREADY_COMPLETED`. `cancel_requested` is also set so a
  worker mid-run can observe it (checked at the top of `_execute`).
- **Retry** (`POST /executions/{id}/retry`) — only from `FAILED`/
  `TIMED_OUT`/`DEAD_LETTERED`; re-queues the *same* execution row (same
  `attempt_count` history) and runs the worker inline again.
- **Replay** (`POST /executions/{id}/replay`) — always allowed; clones a
  *new* execution row with `trigger_type=REPLAY` and
  `parent_execution_id` pointing at the original, fresh `attempt_count`.
  Use replay to re-run a *succeeded* execution's input, or to try a fixed
  input after editing tool assignments — retry re-runs exactly what failed,
  replay lets you start over.
