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

> **Updated for Phase 4.1 (Milestone 4).** Structured tracing now exists —
> see [../observability/architecture.md](../observability/architecture.md).
> The paragraph this replaced also contained a factual error worth recording
> rather than quietly deleting: it said `runtime_events` "carries
> `correlation_id`/`request_id` on every row". The **columns** existed; the
> values did not. Phase 4.1 measured the live database and found
> `correlation_id` null on essentially all ~297,000 rows, and on 74,395 of
> 74,619 `agent_executions`. Nothing populated them — the execution service
> read `correlation_id` only from the request body, and `POST /executions`
> took no `Request` object at all, so no header could reach it. A schema
> column is not a fact; this document had mistaken one for the other.

**Now implemented (Phase 4.1)**: trace and span context across the whole
execution path, stable semantic attributes with a bounded metric-label
allowlist, a non-gating runtime-event contract, and the secret scrubber with
a METADATA_ONLY capture baseline. Spans are **derived** from the domain rows
rather than stored, so a timeline per execution is assembled by walking
foreign keys — `GET /runtime/executions/{execution_id}/trace`.

**Also implemented (Phase 4.4)**: real-cost aggregation and budgets — see
[cost-governance.md](./cost-governance.md) and [budgets.md](./budgets.md).
The cost figures on this page's dashboard are the legacy *estimated*
analytics, now deprecated in place.

**Also implemented (Phase 4.2)**: the trace explorer and full trace assembly —
search executions by trace, agent, version, environment, model, tool, status,
error or time, and reconstruct any single execution's chronology from the
existing rows. See [../observability/tracing.md](../observability/tracing.md).

**Also implemented (Phase 4.6)**: export to an external tracing backend over
OpenTelemetry — execution traces stream to any OTLP collector (Datadog, Grafana,
Splunk, …) through an adapter that keeps the OTel SDK out of the core, fail-open
so a collector outage never affects an execution; and a Prometheus metrics
surface at `GET /metrics` (authenticated, tenant-scoped, bounded-cardinality
labels). See [../observability/opentelemetry.md](../observability/opentelemetry.md)
and [../observability/metrics.md](../observability/metrics.md).

**Still not implemented**: the trace explorer *UI* (deferred to the observability
center, 4.9), and alerting thresholds / SLOs (§82; 4.7 — the metrics surface
4.7 builds on landed in 4.6). The dashboard remains pull-based, not push-based.
