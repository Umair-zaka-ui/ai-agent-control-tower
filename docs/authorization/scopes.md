# Scoped permissions (Phase 4.3.2 §15)

A role assignment carries a **scope**. A grant only counts when its scope *applies* to
the request, so the same role can mean different reach for different people.

| Scope | Applies when |
|-------|--------------|
| `GLOBAL` | always |
| `ORGANIZATION` | the grant's org matches the request's org (defaults to the identity's org) |
| `DEPARTMENT` | the request names a resource in the grant's department |
| `TEAM` | … the grant's team |
| `PROJECT` | … the grant's project |
| `RESOURCE` | the request names exactly the grant's `resource_type` + `resource_id` |

`ScopeResolver.applies(grant, user, resource_ctx)` decides this. The request supplies a
`ResourceContext` (organization / department / team / project / resource-id); a
permission-only check (endpoint gating with no specific resource) passes at most an
organization.

## Worked example (§15)

> John holds `ROLE_AI_OPERATOR` scoped to **Department = Radiology**.
> - `agent.execute` on a **Radiology** agent → the department grant applies → **allow**.
> - `agent.execute` on a **Billing** agent → the department does not match → that grant
>   does not apply; with no other grant, **deny**.

## Narrow scopes and generic checks

Narrower-than-organization grants (department/team/project/resource) do **not** satisfy a
generic, resource-less permission check — they are conditional on naming a matching
target. This is deliberate: a department-scoped role must not silently pass an org-wide
gate. `GLOBAL` and matching `ORGANIZATION` grants (and the legacy fallback, which is
`GLOBAL`) do satisfy generic checks, which is why every pre-4.3 user is unaffected.
