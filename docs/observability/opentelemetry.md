# OpenTelemetry export — the adapter, OTLP, and fail-open semantics

> **Phase 4.6 (ACT-SRS-M4 §4.6, §9, §12, §27, §36).** This document describes
> how the platform's telemetry becomes interoperable with industry tooling
> (Datadog, Azure Monitor, Grafana, Splunk, Elastic, any OTLP collector), and
> the two properties that make that safe: an exporter failure never affects an
> execution, and the buffer that makes retry possible is bounded. The reasoning
> and the rejected alternatives are in
> [ADR-0011](../architecture/adr/0011-opentelemetry-export-as-a-fail-open-plane.md);
> this document is the result.

## What this gives you

Point an OTLP collector endpoint at the platform and your enterprise sees agent
execution traces and operational metrics in the tools you already run. No
runtime change, no vendor SDK in the platform, no lock-in — swapping Datadog for
Grafana for Splunk is editing one config value.

This phase **exports** what phases 4.1–4.5 already produce. It creates no new
telemetry semantics. It builds no telemetry retention
or content policy (4.8), and no operator center (4.9).

## The adapter boundary

```
app/runtime, app/observability        # produce telemetry. import no OTel/vendor SDK.
        │  (no import — export is a downstream reader, not an instrumentation hook)
        ▼
app/telemetry_export/                  # THE adapter. the only package that imports opentelemetry.
├── mapping.py     AssembledTrace  ->  ExportSpan   (neutral records; no OTel types)
├── buffer.py      BoundedSpanBuffer                (bounded, span-counted, policy-on-full)
├── dispatcher.py  ExportDispatcher                 (reads terminal executions; off the hot path)
├── sinks.py       TelemetrySink / OTLPHttpSink     <-- opentelemetry imported HERE, at fn scope, nowhere else
├── metrics.py     MetricsCollector                 (Prometheus exposition; bounded-cardinality labels)
├── config.py      ExportConfig                     (platform default + per-env policy block)
├── health.py      exporter_health                  (in-process, ephemeral; the "errors are visible" half)
├── service.py     TelemetryExportService           (config read/write, audited)
└── routes.py      /api/v1/observability/export/*, GET /metrics
        │
        ▼
your OTLP collector  ->  Datadog / Azure Monitor / Grafana / Splunk / Elastic / …
```

**The anti-lock-in guarantee is structural.** `test_ac02_*` in
`tests/runtime/test_otel_interop.py` walks the AST of every module outside
`app/telemetry_export` and fails on a single `import opentelemetry` (or
`ddtrace`, `datadog`, `prometheus_client`, …). Inside the package, only
`sinks.py` names the SDK, and only inside functions — importing the module does
not pull the SDK. There is no vendor name anywhere in the code, so there is
nothing to change when you switch vendors.

**Exporters are a registry, not a code path.** `sinks._REGISTRY` maps a
*transport* string (`otlp-http`, `null`) to a factory. `register_sink()` adds
one. A future `otlp-grpc`, or a test double, registers without touching the
dispatcher, the buffer, or the service. Vendors are not entries in this
registry — they consume OTLP.

## Fail-open: an exporter failure never affects an execution

Everything else on the execution path fails closed (see
[ADR-0009](../architecture/adr/0009-runtime-governance-as-a-fail-closed-plane.md)).
Export is the deliberate inverse, for the same reason telemetry *capture* is
(ADR-0008): **export is not the business transaction.**

How it holds:

1. **Export is not on the execution path at all.** `ExportDispatcher` reads
   executions that have *already reached a terminal state*, assembles their
   traces through 4.2's read model, and exports them after the fact. The runtime
   is never instrumented. There is no code path from an execution to an export
   to fail along.
2. **Every dispatcher method catches `Exception` and returns.** `collect()`,
   `flush()`, `run_once()` — a broken sink, a malformed row, a hung collector:
   logged at warning, never raised.
3. **A runtime export failure is never an error code.** It surfaces as
   exporter-health state and a metric. The only export error that is ever an
   HTTP error is `EXPORT_CONFIG_INVALID` — a validation failure on a *config
   write*, which an execution never touches.

### The §36 proof

`test_ac05_execution_completes_normally_with_the_collector_down` runs a real
execution, then drives five dispatch cycles with the collector down (every
export attempt raises), and asserts:

- the execution row is byte-for-byte unchanged (status, cost, tokens, timings);
- no telemetry event was written by the export path;
- no audit row was written by the export path;
- `exporter_health` reports `degraded: true` with a non-empty `last_error`;
- the buffer never grew past its capacity.

A companion test (`test_ac05_a_real_otlp_socket_failure_is_contained`) does the
same with a real `OTLPSpanExporter` pointed at a dead port — a genuine
`ConnectionError`, caught in the sink, surfaced as health state, never
propagated.

## Bounded buffering — never an unbounded queue

"Buffer telemetry and retry when the collector recovers" is an unbounded queue
in disguise: a collector down for an hour buffers an hour of spans until the
process OOMs, turning an observability outage into an execution outage.

`BoundedSpanBuffer`:

- has a **hard maximum measured in spans** (`TELEMETRY_EXPORT_BUFFER_MAX_SPANS`,
  default 10,000) — spans are the unit the "memory bounded" claim is about;
- applies a **declared policy when full**:

  | `TELEMETRY_EXPORT_FULL_POLICY` | Behaviour | Use when |
  |---|---|---|
  | `drop_oldest` (default) | Keep the newest spans, drop the oldest | Incident response — you want what's happening *now* |
  | `drop_newest` | Keep the earliest spans, drop the incoming | You care about the *onset* of a slow degradation |
  | `block_bounded` | Wait a short fixed timeout for room, then drop | A collector with brief, frequent hiccups |

- has **no "grow" option** — `BUFFER_FULL_POLICIES` does not contain one, and a
  test asserts that;
- **never holds its lock across the network.** The dispatcher drains a batch
  under the lock, releases it, then calls the sink. A hung collector blocks only
  the dispatcher thread.

"Retry" means: a failed batch is re-queued to the front of the buffer *under the
same cap*. If producers filled the buffer while the export was in flight, the
stale batch loses to the newer data. That is what keeps retry bounded.

## Where export runs

A background dispatcher, opt-in like the connector-health scheduler:

```
TELEMETRY_EXPORT_SCHEDULER_ENABLED=false   # default: no background thread
```

When enabled (typically in a worker process, not the API), `ExportDispatcher.
run_forever()` loops every `TELEMETRY_EXPORT_SCHEDULER_INTERVAL_SECONDS` (30s):

```
run_once()
├── refresh_config()   # re-resolve config; rebuild the sink if endpoint/protocol changed
├── collect()          # SELECT terminal executions since a watermark -> assemble -> convert -> buffer.offer
│                       #   watermark advances on collection (best-effort telemetry; a watermark that
│                       #   only advanced on success would be a retry queue by another name)
└── flush()            # buffer.drain(batch) -> sink.export_spans() -> health.record_success/failure
```

Tests drive `run_once()` directly, exactly as the behavioral-signals tests drive
evaluation directly.

A freshly-started dispatcher looks back
`TELEMETRY_EXPORT_SCHEDULER_LOOKBACK_SECONDS` (300s) and no further — a restart
exports the recent past, not the entire backlog. The watermark is in-process and
ephemeral: on restart, a few minutes of spans may not be exported. That is the
accepted cost of bounded memory (see `RECOVERY.md`).

## Configuration

### Platform default (env vars, set once per deployment)

| Setting | Default | Meaning |
|---|---|---|
| `TELEMETRY_EXPORT_ENABLED` | `false` | Master on/off |
| `TELEMETRY_EXPORT_PROTOCOL` | `otlp-http` | `otlp-http` or `null` — **never a vendor name** |
| `TELEMETRY_EXPORT_OTLP_ENDPOINT` | `""` | e.g. `http://otel-collector:4318/v1/traces` |
| `TELEMETRY_EXPORT_HEADERS` | `{}` | Extra collector headers — where a vendor's auth token goes |
| `TELEMETRY_EXPORT_BUFFER_MAX_SPANS` | `10000` | Hard buffer cap |
| `TELEMETRY_EXPORT_BATCH_SIZE` | `512` | Spans per OTLP request |
| `TELEMETRY_EXPORT_TIMEOUT_SECONDS` | `5.0` | Per-request network timeout |
| `TELEMETRY_EXPORT_FULL_POLICY` | `drop_oldest` | See the table above |
| `TELEMETRY_EXPORT_SCHEDULER_ENABLED` | `false` | Run the background dispatcher |
| `TELEMETRY_EXPORT_SCHEDULER_INTERVAL_SECONDS` | `30.0` | Dispatch cycle |
| `TELEMETRY_EXPORT_SCHEDULER_LOOKBACK_SECONDS` | `300.0` | How far back a fresh dispatcher reads |

### Per-environment override (`Environment.policy["telemetry_export"]`)

A tenant may override `enabled`, `endpoint`, `protocol`, and `headers` per
environment — the same JSONB policy document that already carries allowed
models, change windows, and budgets. Buffer sizing and timeouts stay
platform-level (a tenant tuning the buffer to 1 would turn drop-oldest into
"drop everything" and call it configuration).

```
PUT /api/v1/observability/export/config          # runtime.telemetry.export.manage, audited, idempotent
{
  "environment_id": "…",
  "enabled": true,
  "protocol": "otlp-http",
  "endpoint": "https://otlp.example.com:4318/v1/traces",
  "headers": {"DD-API-KEY": "…"}                  # carried opaquely; never logged/audited/echoed
}
```

`GET /api/v1/observability/export/config?environment_id=…` returns the effective
config with **header names only, never values**, and the audit record for a
change carries the endpoint **host only** (scheme + host + port — no path, no
query, no credential).

Swapping vendors is this call with a different `endpoint`. That is the entire
migration.

### Vendor examples (all the same shape — the collector does the vendor part)

| Vendor | `endpoint` | `headers` |
|---|---|---|
| OpenTelemetry Collector | `http://collector:4318/v1/traces` | — |
| Datadog Agent (OTLP intake) | `http://datadog-agent:4318/v1/traces` | — |
| Grafana Alloy / Tempo | `http://alloy:4318/v1/traces` | — |
| Grafana Cloud (direct) | `https://otlp-gateway-….grafana.net/otlp/v1/traces` | `Authorization: Basic …` |
| Splunk Observability | `https://ingest.<realm>.signalfx.com/v2/trace/otlp` | `X-SF-TOKEN: …` |

## Exporter health

`GET /api/v1/observability/export/health` (`runtime.telemetry.view`):

```json
{
  "exporter": {
    "degraded": true,
    "last_success_at": "…",
    "last_error": "OTLP exporter returned FAILURE for http://collector:4318/v1/traces",
    "last_error_at": "…",
    "consecutive_failures": 4,
    "spans_exported_total": 18234,
    "spans_dropped_total": 512,
    "batches_failed_total": 4
  },
  "platform_default": { … }
}
```

Health is **process-local and ephemeral** — it resets when the process does,
which is honest: the buffer it describes is also gone. It also feeds metrics
(`act_telemetry_export_*`), so a Prometheus-based operator sees export
degradation on the same dashboard as everything else.

## What is exported

Assembled execution traces (4.2), as OTLP spans:

- **Metadata only.** The assembler never reads a content column; `mapping.py`
  re-runs the 4.1 scrubber over every attribute value and drops any attribute
  whose name is sensitive or unlisted-high-cardinality — defense in depth,
  because the thing crossing to a third party is the thing worth checking
  twice. No prompt, no tool argument, no model output, no secret.
- **Deterministic OTLP ids.** The 16-byte trace id and 8-byte span ids are
  hashes of 4.2's ids, so a trace re-exported after a restart is the same trace
  to the collector.
- **A `service.name` of `ai-agent-control-tower`** and, when derivable, a
  `deployment.environment` resource attribute.

Metrics are scraped, not pushed — see [metrics.md](./metrics.md).

## Plane discipline (unchanged)

Export is fail-open telemetry. It is **never** an input to a governance decision
(4.3) and **never** gates an execution. Governance still fails closed. This
phase adds an export path; it does not blur the planes.
