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

## Agent-triggered self-execution (§29, §31)

`POST /api/v1/runtime/executions/self` is the second, narrower entry point
into the same Runtime Gateway: an *agent*, authenticated by its own API key
rather than a human/service session, requesting an execution of **itself**
(e.g. a webhook callback or a tool re-invoking the agent that owns it). The
request body has no `agent_id` field — there is nothing to spoof — the
target is always the calling agent, resolved from `get_current_agent`.

`ExecutionRequestService.request_execution_as_agent` shares the exact same
pipeline as `request_execution` (deployment resolution, input-contract
validation, idempotency, policy evaluation, approval, queueing — see the
state-machine walk above), factored into a common `_request_execution`
helper parameterized on `principal: User | Agent`. The one real difference
is authorization: a human/API request goes through
`AuthorizationGateway.authorize` (RBAC + ABAC), while a self-execution
request goes through `AuthorizationGateway.authorize_agent` (ABAC only — an
agent holds no RBAC role of its own to check), with `trigger_type=AGENT` on
the resulting execution row so it's distinguishable in the audit trail and
Execution Detail page from human- or API-triggered runs.

This is deliberately **self-only**: an agent may request an execution of
itself, never of another agent. Arbitrary agent-to-agent chaining is
multi-agent orchestration, which is explicitly out of scope for this phase
(see "What's deliberately not here" in [overview.md](overview.md)).

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
