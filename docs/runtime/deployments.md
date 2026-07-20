# Deployments

`/runtime/deployments` · `runtime.deployment.*` permissions.

## Environments (§13)

`DEVELOPMENT`, `TEST`, `STAGING`, `PRODUCTION`, `SANDBOX`. Each
`agent_deployments` row belongs to exactly one agent, one published version,
and one environment; `runtime_limits` and `configuration` are per-deployment
JSONB, so the same version can run under different limits in STAGING vs.
PRODUCTION.

## Lifecycle (§14) and the RECREATE strategy (§15)

```
CREATED → (PENDING_APPROVAL) → DEPLOYING → HEALTH_CHECKING → ACTIVE
                                              ├─→ SUSPENDED → ACTIVE (resume)
                                              ├─→ ROLLING_BACK → ACTIVE
                                              └─→ RETIRED
```

`DeploymentService.deploy()` implements **RECREATE** only — `CANARY`,
`ROLLING` and `BLUE_GREEN` are valid values for `deployment_strategy` (the
data model supports them per §15) but all currently execute as RECREATE:
any other `ACTIVE` deployment for the same agent+environment is retired,
then the new one goes `DEPLOYING → HEALTH_CHECKING → ACTIVE` synchronously.
Building the other strategies is future work; nothing in the schema blocks
it (`active_replicas`/`desired_replicas` are already tracked per
deployment).

## Deployment-level approval

If `agent.criticality == MISSION_CRITICAL` and `environment == PRODUCTION`,
`deploy()` does not proceed on the first call: it creates a
`runtime_approvals` row (`requested_action=DEPLOYMENT`) and returns the
deployment in `PENDING_APPROVAL`. Deciding that approval
(`POST /approvals/{id}/decide`) moves the deployment back to `CREATED` on
approval (so a second `POST /deployments/{id}/deploy` actually deploys it)
or to `FAILED` on rejection — a terminal state that never silently becomes
deployable again just because someone calls `/deploy` again. This is
distinct from *execution*-level approval on the same criticality+environment
combination — see [runtime-policy-and-approvals.md](runtime-policy-and-approvals.md).

## Rollback (§57)

`POST /deployments/{id}/rollback {target_version_id}` — the target must be
one of this agent's own versions and must be `PUBLISHED` or `DEPRECATED`
(`ROLLBACK_NOT_AVAILABLE` otherwise, e.g. you cannot roll back to a
`REVOKED` version). Rollback repoints `agent_version_id` on the *same*
deployment row and goes back to `ACTIVE` — it never edits a historical
version. Automatic rollback on failure-rate/latency thresholds (§58) is
modeled in intent but not implemented; it ships disabled by default per the
SRS regardless.

## Health

`health_status` (`UNKNOWN`/`HEALTHY`/`DEGRADED`/`UNHEALTHY`/`OFFLINE`) is
set to `HEALTHY` on a successful deploy and updated by
`POST /deployments/{id}/heartbeat`; samples are kept in `deployment_health`
and shown on the deployment detail page. See
[health-and-observability.md](health-and-observability.md).
