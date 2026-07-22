# Agent registry & lifecycle

`/runtime/agents` · requires `runtime.agent.view`; mutations require the
matching `runtime.agent.*` permission (§67).

> **Superseded by Phase 5.1.** The 8-state lifecycle and endpoint table
> originally documented here (`DRAFT → VALIDATING → VALIDATED → APPROVED →
> ACTIVE → {SUSPENDED, DEPRECATED, ARCHIVED} → RETIRED`, with `validate`/
> `approve`/`deprecate` each borrowing a neighboring transition's audit
> event) has been replaced by the full 13-state registry lifecycle — see
> [registry/lifecycle.md](registry/lifecycle.md) for the current state
> machine, and [registry/overview.md](registry/overview.md) for the whole
> Phase 5.1 registry. This file's registration/criticality/tenant-isolation
> notes below still apply unchanged.

## Registration

`POST /api/v1/runtime/agents` creates the `agents` row (with
`lifecycle_status=DRAFT`) and its first `agent_definitions` row in one call —
name, description, framework, entrypoint, schemas and system instructions.
Definitions are versioned independently of `agent_versions`: a new
`AgentDefinition` can be created and later referenced by a version, but
most agents only ever need the one created at registration. Phase 5.1
extends the registration payload considerably — see
[registry/registration.md](registry/registration.md).

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
