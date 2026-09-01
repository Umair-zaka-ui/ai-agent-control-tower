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

**Also implemented (Phase 4.7)**: runtime SLOs (SLI / target / window / error
budget) evaluated deterministically, and a first-class alert lifecycle
(OPEN → ACKNOWLEDGED → RESOLVED → SUPPRESSED) that an SLO breach or a significant
behavioral finding raises — deduplicated so one condition is one alert. It is a
signal, not a notification: nothing here delivers an alert anywhere. See
[`../operations/slos.md`](../operations/slos.md) and
[`../operations/alerts.md`](../operations/alerts.md).

**Also implemented (Phase 4.8)**: telemetry capture policy
(`METADATA_ONLY` / `REDACTED_CONTENT` / `FULL_CONTENT` / `DISABLED`) per tenant /
environment / agent / classification, defaulting conservatively; trace **content**
served from `GET /api/v1/observability/traces/{trace_id}/content` — scrubbed of
secrets, redacted per classification, chain-of-thought never included — gated by
`runtime.trace.content.view` (a distinct, stronger permission, audited on every
use); and per-class retention with a safe, idempotent expiration sweep. See
[`../observability/privacy.md`](../observability/privacy.md) and
[`../observability/retention.md`](../observability/retention.md).

**Also implemented (Phase 4.9)**: the **Enterprise Runtime Governance &
Observability Center** — nine per-persona operator views over the 4.1–4.8
engines (Runtime Overview, Trace Explorer, Trace Detail, Cost Center, Governance
Decisions, Behavior & Anomalies, SLO Dashboard, Alert Center, Telemetry Policy).
Read + trigger only; the Trace Detail content pane renders content only to
`runtime.trace.content.view` holders, through 4.8's audited endpoint. See
[`../operations/observability-center.md`](../operations/observability-center.md).

**Also demonstrated (Phase 4.10)**: the **§33 end-to-end proof** — one real
governed execution threading trace → governance (mid-loop stop) → cost (budget
in bound) → redaction → audit → OTLP export — plus tenant privacy, the budget
race, and both plane directions (telemetry fails open, governance fails closed).
All fifteen §41 completion gates are closed. **Milestone 4 is complete.** See
[`milestone-4-proof.md`](./milestone-4-proof.md).

**Still not implemented**: **notification delivery** for alerts (a future
integration — 4.7 built the signal, not the notifier). The dashboard remains
pull-based, not push-based.
