# Authorization Middleware

Phase 4.3.6 introduces one centralized enforcement layer for every protected
operation in the AI Agent Control Tower. No API route, background worker,
scheduled job, workflow node, AI agent execution or external integration
bypasses it.

## What it replaces

Before 4.3.6, enforcement points called the underlying engines directly:
`require_permission` used the permission cache, `/authorization/check` inlined
the RBAC → resource → ABAC layering, and the agent runtime only knew the
Phase-2 governance pipeline. Now **everything calls the
[Authorization Gateway](gateway.md)** (`app/authorization/middleware/`), which
runs the [pipeline](pipeline.md) in one deterministic order and returns one
normalized decision object.

## Enforcement points

| Surface | How it enforces |
| --- | --- |
| REST APIs | `Depends(require_permission("code"))` → `AuthorizationGateway.authorize(...)` |
| Explicit check | `POST /api/v1/authorization/check` → same gateway call, decision returned to the caller |
| Background workers | `AuthorizationGateway.authorize_background(principal_id, permission, source="WORKER")` |
| Scheduled jobs | same, `source="SCHEDULER"` |
| Workflow runtime | same, `source="WORKFLOW"` — one call per node before it executes |
| AI agent runtime | `process_agent_action` → `AuthorizationGateway.authorize_agent(...)` (ABAC layer over the Phase-2 baseline) |
| External integrations | agent API keys authenticate; `/agent-actions` runs the full agent path |

The route dependency attaches the decision to `request.state.authorization` so
handlers can honour constraint obligations (mask fields, limit parameters)
without re-evaluating anything.

## Decision semantics

- The gateway **never grants what the baseline denied** — RBAC/resource deny is
  final (default deny, §36).
- On a baseline allow, ABAC may deny, challenge (`REQUIRE_APPROVAL`,
  `REQUIRE_MFA`, `REQUIRE_JUSTIFICATION`) or constrain (`MASK_FIELDS`,
  `LIMIT_ACTION`).
- A `REQUIRE_JUSTIFICATION` challenge is satisfiable in-band: repeat the request
  with an `X-Justification` header; the justification is audited.
- Challenges surface as typed §25/§26 errors
  (`APPROVAL_REQUIRED`, `MFA_REQUIRED`, `JUSTIFICATION_REQUIRED`) in the
  standard error envelope; a plain deny keeps the legacy 403 contract.

## Caching

Final decisions are cached per identity × permission × resource × organization
× RBAC-version × ABAC-generation with a short TTL. Any role/assignment change,
policy change or session revocation invalidates instantly (the key rotates or
the identity epoch bumps). Dynamic-context evaluations and challenge decisions
are never cached. See [gateway](gateway.md#decision-cache).

## Observability

`GET /api/v1/authorization/middleware/metrics` exposes request counts, deny /
approval / MFA counters, latency (avg, p95), pipeline errors and the decision
cache hit ratio (§34). Every evaluation carries a request id and correlation
id; sensitive attribute values never appear in logs (§35, §36).

## Frontend

`AuthorizationProvider` (wrapping the 4.3.2 `PermissionProvider`) routes
gateway decisions and typed API errors to the matching UI (§33): approval
dialog, MFA challenge, justification prompt, masked rendering and action
limits. `AuthorizationErrorBoundary` catches unhandled authorization failures;
`PermissionGuard` guards routes. See [obligations](obligations.md).
