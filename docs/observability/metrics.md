# Metrics surface — Prometheus exposition with bounded cardinality

> **Phase 4.6 (ACT-SRS-M4 §4.6, §12).** The operational metrics surface for
> OTLP/Prometheus-compatible consumers, and the rule that keeps it from taking
> a metrics backend down: **every label is a bounded-cardinality dimension.**

## Pull, not push

`GET /metrics` returns Prometheus text exposition (format `0.0.4`). A metrics
value is state-shaped — "how many executions failed in the last hour, by
provider" — and the natural way to publish state is to let a scraper read it on
its own clock. Pushing metrics over OTLP would add a second export loop with its
own backpressure problem for no benefit: the collector already knows how to
scrape.

Traces are the opposite (event-shaped, and the platform is the only thing that
has them at the moment they happen), which is why spans are **pushed** over OTLP
and metrics are **scraped**.

## Exposure model

`GET /metrics` is:

- **authenticated** — it requires `runtime.telemetry.view` like any other
  telemetry read;
- **tenant-scoped** — it returns the calling principal's organization's numbers
  and no one else's. Every domain query leads with `organization_id`.

This is deliberately **not** the "open unauthenticated scrape target" model. On
a multi-tenant platform an unauthenticated `/metrics` is a cross-tenant
disclosure. A collector scrapes this endpoint with a service credential, the
same as any other authenticated API. The process-level exporter-health gauges it
also emits carry no tenant data at all.

## Bounded cardinality is the whole point

A time-series database allocates one series per distinct combination of label
values. Put an `execution_id` on a counter and you do not get a counter — you
get one series per execution, forever, and the metrics backend falls over. The
cost is not linear in traffic; it is the product of every label's cardinality.

So **every label** on every metric here goes through `metric_label_set()`, which
reuses 4.1's denylist
([`app/observability/attributes.py`](../../backend/app/observability/attributes.py)):

1. a name in `SENSITIVE_ATTRIBUTES` (`email`, `prompt`, `tool_args`, …) — raises;
2. a name in `HIGH_CARDINALITY_ATTRIBUTES` (`execution_id`, `agent_id`,
   `trace_id`, raw `model`, …) — raises: it belongs on a trace, not a metric;
3. anything not in the allowed set — raises.

The allowed set is 4.1's `METRIC_DIMENSIONS`:

| Dimension | Cardinality source |
|---|---|
| `environment` | per-tenant config — a handful |
| `status` | the execution state enum |
| `provider` | the model-provider registry |
| `model_category` | the vendor *family* (`gpt`, `claude`, `llama3`), never the raw model string |
| `error_class` | this codebase's error taxonomy |

plus a small, explicitly-declared 4.6 extension (`_EXPORT_BOUNDED_DIMENSIONS`)
for the two behavioral-finding enums, each a closed vocabulary the platform
owns:

| Dimension | Values |
|---|---|
| `signal_type` | the 7-member `SIGNAL_TYPES` tuple |
| `state` | `NORMAL / DEGRADED / ANOMALOUS / INSUFFICIENT_DATA / UNKNOWN` |

These are declared in 4.6, **not** added to `METRIC_DIMENSIONS`, because they
are meaningful only on the behavioral metric and must not become legal labels on
an execution counter.

`test_ac04_every_metric_add_call_uses_only_bounded_labels` parses `metrics.py`
and checks every `r.add(...)` call's keywords against the allowed set. A future
edit adding `execution_id=…` to a metric fails there, not in production.

## The metrics

All values are **windowed gauges** unless marked otherwise — "in the last N
seconds" (default 3600, override with `?window_seconds=`), derived at scrape
time from existing rows with ordinary `GROUP BY`. No new metric-source table, no
per-execution series.

### From `agent_executions`

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `act_runtime_executions` | gauge | `environment, status, provider, model_category` | Terminal executions in the window |
| `act_runtime_execution_duration_ms_sum` | gauge | same | Summed duration (ms) — pair with `_count` for an average |
| `act_runtime_execution_duration_ms_count` | gauge | same | Executions contributing to the sum |
| `act_runtime_spend_usd` | gauge | same | Summed real (non-estimated) cost, USD |

### From `behavioral_findings`

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `act_runtime_behavioral_findings` | gauge | `signal_type, state` | Findings evaluated in the window |

### Process-level export health (no tenant data)

| Metric | Type | Meaning |
|---|---|---|
| `act_telemetry_export_spans_exported_total` | counter | Spans delivered since process start |
| `act_telemetry_export_spans_dropped_total` | counter | Spans dropped by the bounded buffer |
| `act_telemetry_export_batches_failed_total` | counter | Failed export attempts |
| `act_telemetry_export_degraded` | gauge | `1` when the last export attempt failed |
| `act_telemetry_export_consecutive_failures` | gauge | Consecutive failed attempts |

## Why gauges and not counters for the domain metrics

A true Prometheus counter is monotonic since process start. These numbers are
derived from a database at scrape time, so they cannot be monotonic without the
platform tracking per-process deltas it has no reason to track. Windowed gauges
are the honest representation, and they are what a `postgres_exporter`-style
"query the DB and expose the result" surface produces. The `rate()`-style
questions ("failures per minute") are answered by the collector differencing
successive scrapes of the window, or — better — from the pushed span stream.

## Not in this phase

SLOs and alerting shipped in **Phase 4.7**, on top of this surface's *source of truth* (the domain rows) rather than the scraped gauges — see [`../operations/slos.md`](../operations/slos.md). This surface still only exposes numbers; it does not decide what a bad number is. A metrics *storage* backend (a
TSDB) is out entirely — the customer's collector stores; the platform exposes.
