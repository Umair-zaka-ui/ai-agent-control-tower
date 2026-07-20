# Architecture

## Control plane vs. execution plane

```
Control Plane                          Execution Plane
  Agent Registry                         Runtime Gateway
  Version Management                     Scheduler / Queue
  Deployments                            Worker
  Runtime Policy                         Tool Gateway
  Approvals                              Model Gateway
  Monitoring                             Telemetry
```

The control plane manages desired state (`app/runtime/services.py`'s
`AgentRegistryService`, `AgentVersionService`, `DeploymentService`); the
execution plane performs the work (`ExecutionRequestService`,
`ExecutionWorkerService`, `ModelGatewayService`, `ToolGatewayService`).

## Why `agents` is not forked

The platform already had an `agents` table (Phase 1) representing "the AI
agents whose actions are governed," wired into 20+ authorization/governance
call sites, plus `agent_identities` (Phase 4.2) for its credential posture.
The Phase 5 SRS's own §7.1 "Agent" entity is the same conceptual thing from
a *runtime lifecycle* angle — not a new agent.

So `agents` gained additive columns instead of a parallel `runtime_agents`
registry: `slug`, `project_id`, `owner_type`/`owner_id`, `criticality`,
`data_classification`, `default_environment`, `lifecycle_status`,
`archived_at`. The pre-existing `status` column (ACTIVE/INACTIVE/SUSPENDED/
ARCHIVED/BLOCKED) keeps its original governance/API-key meaning; the new
`lifecycle_status` (DRAFT..ACTIVE..RETIRED, see
[agent-lifecycle.md](agent-lifecycle.md)) is a distinct, additive concept
layered on the same row. Every new table (`agent_definitions`,
`agent_versions`, `agent_deployments`, `agent_executions`, …) foreign-keys
to `agents.id`.

## Why the Runtime Gateway calls the existing `AuthorizationGateway`

`app/authorization/middleware/gateway.py`'s own docstring names "agent
runtime" as a caller of `AuthorizationGateway.authorize*` — the Phase
4.3.6 pipeline (Authentication → Identity → RBAC → Resource → ABAC →
Obligations → Audit → Cache) was already built to be this module's baseline
authorization step. `ExecutionRequestService.request_execution` calls
`AuthorizationGateway(db).authorize(actor, "runtime.execution.create",
resource_type="agent", resource_id=agent.id, ...)` before anything is
queued; Runtime Policy (limits, approved models, environment restrictions)
is evaluated *after* that baseline passes, exactly as §4.4 orders it.

## Why the queue has no new infrastructure

§30 explicitly allows "PostgreSQL-backed queue for development." Rather than
add a Redis/Celery dependency to this environment, the queue *is*
`agent_executions` — a worker claims a row with
`SELECT ... FOR UPDATE SKIP LOCKED WHERE status = 'QUEUED'`, and
`execution_locks` holds the lease (§32). See
[workers-and-queue.md](workers-and-queue.md) for the claim/heartbeat/retry
mechanics, and for how this environment drives the worker (inline, eagerly,
right after enqueueing — no standalone process).

## Module layout

```
backend/app/runtime/
  __init__.py
  schemas.py     Pydantic request/response models
  services.py     every service class (registry, versioning, deployments,
                   runtime gateway, worker, gateways, policy, approvals,
                   health, kill switch, dashboard)
  routes.py       the /api/v1/runtime router

frontend/src/modules/runtime/
  RuntimeDashboardPage.tsx, AgentsPage.tsx, AgentDetailPage.tsx,
  DeploymentsPage.tsx, DeploymentDetailPage.tsx,
  ExecutionsPage.tsx, ExecutionDetailPage.tsx,
  CapabilitiesPage.tsx, ToolsPage.tsx, ApprovalsPage.tsx, OperationsPage.tsx,
  components/RuntimeNav.tsx, utils.ts, index.ts
```

This mirrors the flat governance-module shape (`app/governance/{schemas,
services,routes}.py`) rather than the deeper directory tree sketched in the
SRS's illustrative §63 — the codebase's real convention for a new domain
module is one file per concern, not one file per sub-capability.
