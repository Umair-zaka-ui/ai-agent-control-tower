# Operations Center & the kill switch

`/runtime/operations` · deployment health + workers require
`runtime.health.view`; the kill switch requires the separate, more
sensitive `runtime.kill_switch.execute` permission (§60 — "high-privilege
authorization").

## Scopes

§60 lists five scopes: Execution, Agent, Project, Organization, Platform.
All five are implemented.

```
POST /kill-switch/executions/{execution_id}     {reason}
POST /kill-switch/agents/{agent_id}              {reason}
POST /kill-switch/projects/{project_id}          {reason}
POST /kill-switch/organizations/{organization_id}   {reason}
POST /kill-switch/platform                       {reason}
```

- **EXECUTION** — cancels that one execution if not already terminal.
- **AGENT** — sets `agent.lifecycle_status = SUSPENDED` *and* cancels every
  active execution (`QUEUED`/`RUNNING`/`PENDING_APPROVAL`/…) for that agent
  in one call — a suspended agent with executions still running would be a
  kill switch that didn't actually kill anything.
- **PROJECT** — resolves every agent with that `project_id` in the actor's
  organization, suspends all of them, cancels their active executions, and
  suspends their active deployments. Empty project (no agents, or none in
  this organization) is rejected rather than silently succeeding.
- **ORGANIZATION** — cancels every active execution *and* suspends every
  active deployment org-wide. The route double-checks
  `organization_id == actor.organization_id` even though `require_permission`
  already scopes the actor — activating another organization's kill switch
  is rejected with `PERMISSION_DENIED`, not merely relying on the caller
  not knowing another org's ID.
- **PLATFORM** — cross-tenant: cancels every active execution and suspends
  every active deployment across *every* organization. Because
  `runtime.kill_switch.execute` is granted per-organization like every
  other runtime permission, holding it is **not** sufficient for this
  scope — `KillSwitchService.activate` additionally requires the actor's
  legacy `role` to be `SUPER_ADMIN` before it will even look outside the
  actor's own organization. A permission scoped to one tenant must never
  be enough, by itself, to halt every tenant's executions.

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
