# Operations Center & the kill switch

`/runtime/operations` · deployment health + workers require
`runtime.health.view`; the kill switch requires the separate, more
sensitive `runtime.kill_switch.execute` permission (§60 — "high-privilege
authorization").

## Scopes actually implemented

§60 lists five scopes: Execution, Agent, Project, Organization, Platform.
This build implements **Execution, Agent and Organization** —
`runtime.kill_switch.execute` is granted per-organization (like every other
runtime permission), so a *Platform*-wide switch would need a separate
cross-tenant super-admin surface that doesn't exist yet, and *Project*
scope would need to resolve every agent under a project first (the `Project`
model exists from the org-hierarchy phase, but that join isn't built here).
Both are natural follow-ups, not architectural dead ends — `KillSwitchService`
already takes a `scope` string and dispatches on it, so adding a case is
additive.

```
POST /kill-switch/executions/{execution_id}   {reason}
POST /kill-switch/agents/{agent_id}           {reason}
POST /kill-switch/organizations/{organization_id}   {reason}
```

- **EXECUTION** — cancels that one execution if not already terminal.
- **AGENT** — sets `agent.lifecycle_status = SUSPENDED` *and* cancels every
  active execution (`QUEUED`/`RUNNING`/`PENDING_APPROVAL`/…) for that agent
  in one call — a suspended agent with executions still running would be a
  kill switch that didn't actually kill anything.
- **ORGANIZATION** — cancels every active execution *and* suspends every
  active deployment org-wide. The route double-checks
  `organization_id == actor.organization_id` even though `require_permission`
  already scopes the actor — activating another organization's kill switch
  is rejected with `PERMISSION_DENIED`, not merely relying on the caller
  not knowing another org's ID.

Every activation is both audited (`RUNTIME_KILL_SWITCH_ACTIVATED`,
`AuthorizationAudit`) and recorded as a `CRITICAL`-severity `runtime_events`
row with `reason` and the count of executions cancelled — §60's "full audit
event" and "clear recovery process" (recovery here is: reactivate the
agent/deployment explicitly once the incident is resolved; the kill switch
never auto-recovers).

## Frontend confirmation

The Operations page requires a non-empty `reason` before any kill-switch
button is enabled, and wraps the actual call in `window.confirm(...)` with
an explicit "cannot be undone" warning — consistent with how other
destructive actions in this app (e.g. deleting an agent from the legacy
`/agents` list) are confirmed. There is no silent one-click kill switch
anywhere in the UI.
