# Agent registry & lifecycle

`/runtime/agents` · requires `runtime.agent.view`; mutations require the
matching `runtime.agent.*` permission (§67).

## Registration

`POST /api/v1/runtime/agents` creates the `agents` row (with
`lifecycle_status=DRAFT`) and its first `agent_definitions` row in one call —
name, description, framework, entrypoint, schemas and system instructions.
Definitions are versioned independently of `agent_versions`: a new
`AgentDefinition` can be created and later referenced by a version, but
most agents only ever need the one created at registration.

## Lifecycle state machine (§10)

```
DRAFT → VALIDATING → VALIDATED → APPROVED → ACTIVE
                                              ├─→ SUSPENDED ─┐
                                              ├─→ DEPRECATED │
                                              └─→ ARCHIVED ──┼─→ RETIRED
                                                              ┘
```

Implemented as synchronous transitions in `AgentRegistryService` — this
environment has no long-running validation job, so `validate()` runs its
checks (a definition exists) and moves `DRAFT → VALIDATED` in the same
request rather than passing through an async `VALIDATING` step. Every
transition is audited (`RUNTIME_AGENT_*` events, both
`AuthorizationAudit` and `runtime_events`).

| Endpoint | From | To |
|---|---|---|
| `POST /agents/{id}/validate` | DRAFT | VALIDATED |
| `POST /agents/{id}/approve` | VALIDATED | APPROVED |
| `POST /agents/{id}/activate` | APPROVED or SUSPENDED | ACTIVE |
| `POST /agents/{id}/suspend` | ACTIVE | SUSPENDED |
| `POST /agents/{id}/deprecate` | ACTIVE or SUSPENDED | DEPRECATED |
| `POST /agents/{id}/archive` | DEPRECATED, SUSPENDED or ACTIVE | ARCHIVED |
| `POST /agents/{id}/retire` | anything but RETIRED | RETIRED (sets `archived_at`) |

Only `ACTIVE` agents can have executions requested against them
(`AGENT_NOT_ACTIVE`); `SUSPENDED` agents are explicitly rejected
(`AGENT_SUSPENDED`) even though it overlaps with "not active," so a caller
can tell "never got there" from "was stopped" — see
[executions.md](executions.md).

## Criticality and data classification

`criticality` (LOW/MEDIUM/HIGH/MISSION_CRITICAL) and `data_classification`
drive: risk scoring (§56), whether a deployment/execution needs approval
(MISSION_CRITICAL + PRODUCTION always does, see
[runtime-policy-and-approvals.md](runtime-policy-and-approvals.md)), and the
retry policy (denials on a MISSION_CRITICAL agent are never silently
retried more aggressively than any other agent — criticality affects
*gating*, not retry counts).

## Tenant isolation

Every lookup filters on `agent.organization_id == actor.organization_id`;
an agent from another organization returns `AGENT_NOT_FOUND` (404), never a
403 that would leak existence. Covered by
`test_agent_not_found_is_tenant_scoped`
(`backend/tests/authorization/test_runtime.py`).
