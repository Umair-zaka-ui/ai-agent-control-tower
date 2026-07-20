# Runtime policy & human approval

## Runtime Policy Engine (§38, §46-§48)

`RuntimePolicyService.evaluate(agent, version, deployment)` runs *after*
the `AuthorizationGateway` baseline (RBAC/ABAC) has already allowed the
request — it's the runtime-specific layer on top, per §38's "Runtime
policies supplement ABAC." No new table backs this: policy configuration
lives in JSONB already on the entities it governs, so a deployment's limits
travel with the deployment and a version's policy travels with the
(immutable) version.

- **`deployment.runtime_limits`** (§46-§48), all enforced on every request:
  - `maximum_concurrent_executions` — counts `QUEUED`/`RUNNING`/`SCHEDULED`
    executions for this deployment (excluding the request being evaluated
    itself — see below).
  - `maximum_executions_per_minute` — counts executions created in the
    trailing 60 seconds for this deployment.
  - `maximum_cost` — a rolling daily budget: sums `cost` for this
    deployment since midnight UTC.
  - `maximum_tokens` — a pre-flight estimate (the same `len(json)//4`
    heuristic the Model Gateway uses post-hoc, applied *before* any model
    call) rejects a request whose input alone would already exceed the
    per-execution token budget.
  - `maximum_retries` is also read from here by the worker's retry policy
    (see [workers-and-queue.md](workers-and-queue.md)), and
    `maximum_execution_seconds` by its timeout enforcement (see
    [executions.md](executions.md)).

  Any limit that's exceeded saves the execution as `BLOCKED`
  (`RUNTIME_RATE_LIMITED` or `RUNTIME_BUDGET_EXCEEDED`) rather than
  queuing it. Every count query explicitly excludes the execution row
  being evaluated (`exclude_execution_id`) — that row is already flushed
  (it needs an id before this point), so without the exclusion every
  request would count against its own limit before it had even been
  decided, blocking the very first request against a `maximum_..._per_...`
  limit of 1.
- **`version.policy_snapshot`** (immutable, part of the checksum — see
  [versioning.md](versioning.md)): `approved_models` (a model not on the
  list → `MODEL_NOT_APPROVED`), `prohibited_environments` (execution
  outright refused → `RUNTIME_POLICY_DENIED`), and
  `requires_approval_environments`.

A `PolicyResult` carries `allowed`, `requires_approval` and a reason/code —
`allowed=False` short-circuits to `BLOCKED` before approval is ever
considered; `requires_approval=True` (either from the policy snapshot, or
unconditionally for `MISSION_CRITICAL` + `PRODUCTION`) routes to the
approval flow below instead of the queue.

## Human approval (§39)

`runtime_approvals` is a purpose-built table for this — the pre-existing
`Approval` model (Phase 3) is 1:1 with `agent_action_id` (a unique FK) and
can't represent a deployment- or execution-scoped approval without forcing
an artificial `AgentAction` row into existence for every runtime approval.
Same shape either way: `requested_action` (`DEPLOYMENT` or `EXECUTION`),
`risk_score`, `reason`, `status` (`PENDING`/`APPROVED`/`REJECTED`).

`RuntimeApprovalService.decide` resumes whatever it gated:

- `EXECUTION` + `APPROVED` → the execution goes `PENDING_APPROVAL → QUEUED`
  and the worker runs inline immediately (same eager-queue behavior as a
  fresh request).
- `EXECUTION` + `REJECTED` → `REJECTED`, terminal.
- `DEPLOYMENT` + `APPROVED` → the deployment goes back to `CREATED` so a
  second `/deploy` call actually deploys it.
- `DEPLOYMENT` + `REJECTED` → `FAILED`, terminal (see
  [deployments.md](deployments.md) for why this is `FAILED` and not a
  silent reset to `CREATED`).

`/runtime/approvals` (`runtime.approval.review`) lists everything
`PENDING` for the organization and lets a reviewer decide with an optional
comment, persisted as `decision_comment`.
