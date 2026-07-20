# Security

## Default deny (§4.2, §36)

An agent may not execute, invoke a model, or call a tool unless explicitly
allowed at every layer: agent must be `ACTIVE`, deployment must be
`ACTIVE`, version must be `PUBLISHED`/not `REVOKED`, the
`AuthorizationGateway` baseline must allow the caller, Runtime Policy must
allow the request, and (for tools specifically) an `APPROVED` assignment
with the requested action must exist. Any one of these failing blocks the
request; nothing "fails open." An ABAC/policy evaluation error is treated
as a denial, never an allow (inherited from the underlying
`AuthorizationGateway`, which fails closed on internal errors too).

## Tenant isolation

Every service method takes `actor: User` and filters every query on
`organization_id == actor.organization_id` (or, for global catalogs like
`capabilities`, has no organization concept at all and is intentionally
shared). A resource from another organization returns `*_NOT_FOUND` (404),
never a 403 — a 403 would confirm the resource exists, which is itself a
disclosure. Verified for agents (`test_agent_not_found_is_tenant_scoped`)
and the kill switch (`test_kill_switch_cross_org_denied`).

## Immutability & tamper detection

Published versions are immutable; `publish()` recomputes and compares the
checksum before allowing the transition (see
[versioning.md](versioning.md)). This catches direct database tampering
(a row edited outside the API) as well as any future code path that might
try to mutate a published version's snapshot fields.

## Secrets (§45)

`agent_deployments.secret_references` is JSONB expected to hold reference
strings (`{"secret_reference": "vault://production/openai/api-key"}`), never
raw credential values — there is no code path in this module that writes a
literal secret into any table, and the Model Gateway's `MOCK` adapter never
needs one (see [gateways.md](gateways.md)). A real provider adapter would
resolve the reference through a `SecretsResolver` at invocation time, never
storing the decrypted value beyond that call.

## Kill switch & suspension as security controls

`runtime.kill_switch.execute` is a separate, more sensitive permission from
every other `runtime.*` code, deliberately not granted by `ROLE_RUNTIME_OPERATOR`
(see [../../backend/app/authorization/catalog.py](../../backend/app/authorization/catalog.py))
— an operator can register, version and run agents but cannot halt the
entire runtime; only `ROLE_RUNTIME_ADMIN` (and platform-level roles that
inherit it) can. Verified by `test_runtime_operator_role_is_scoped`.

## What this build does not attempt

No sandboxing/isolation between agent executions beyond database-row
tenant scoping (there is no code execution surface in this build — the
Model Gateway is a mock, the Tool Gateway's only working action is
`echo`); no rate limiting below the `maximum_executions_per_minute`/
`maximum_concurrent_executions` policy fields (which are read but only the
concurrency one is currently enforced — see
[runtime-policy-and-approvals.md](runtime-policy-and-approvals.md)); no
MFA step-up for high-risk operations (§78 mentions it as a possibility, not
a requirement, and the platform's existing MFA infrastructure is not yet
wired into this module).
