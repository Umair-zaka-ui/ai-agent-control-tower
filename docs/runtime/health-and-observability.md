# Health, telemetry & the dashboard

## Heartbeats & health (§49, §50)

`POST /deployments/{id}/heartbeat {worker_id, status, metrics}` inserts a
`deployment_health` row and updates `deployment.health_status`.
`HealthMonitoringService.workers()` derives a *platform-wide* worker list
by grouping `deployment_health` on `worker_id` and taking the latest
`checked_at`; status is derived from age, not stored:

- `< 120s` → `HEALTHY`
- `120s-300s` → `DEGRADED`
- `> 300s` (or no heartbeat at all) → `OFFLINE`

This environment's inline worker (see
[workers-and-queue.md](workers-and-queue.md)) never calls the heartbeat
endpoint itself — it runs synchronously inside the request that enqueued
it, so there's nothing to heartbeat. The Operations page says as much
rather than showing a misleadingly empty "workers" table with no
explanation. An out-of-process poller would call this endpoint on a timer
the way §50 describes.

## Telemetry & cost (§51-§55)

No separate metrics/telemetry table — everything the dashboard needs is
derivable from `agent_executions` and `tool_calls` directly:
`RuntimeDashboardService.snapshot` aggregates counts by status, a 7-day
execution trend (`date_trunc('day', created_at)`), average queue time
(`started_at - queued_at` over the last 100 executions with both set),
average execution time (`duration_ms` over the last 100 completed), and
`cost` summed for today. `model_usage`/`tool_usage` JSONB on each execution
row hold the per-call token/cost breakdown for the Execution Detail page.

## The dashboard (§70)

`/runtime` — KPI tiles (registered/active agents, active deployments,
running/queued executions, failed-in-24h, pending approvals, suspended
agents, cost today, success rate, avg queue/execution time) plus the trend
and status-distribution charts, refetched every 15s
(`refetchInterval: 15000` on the frontend query) so it reads as live
without a websocket.

## What's not implemented

Structured tracing/spans (§54) and Prometheus-style metric names (§52) are
not wired up — `runtime_events` (see [architecture.md](architecture.md))
carries `correlation_id`/`request_id` on every row, which is enough to
reconstruct a timeline per execution (shown on the Execution Detail page's
event list) but is not exported to an external tracing backend. Alerting
thresholds (§82) are not implemented; the dashboard is pull-based, not
push-based.
