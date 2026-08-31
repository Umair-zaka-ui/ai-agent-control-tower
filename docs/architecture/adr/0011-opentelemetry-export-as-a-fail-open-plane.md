# ADR-0011 — OpenTelemetry export is a fail-open plane behind a replaceable adapter

- **Status:** Accepted
- **Date:** 2026-08-31
- **Deciders:** Phase 4.6 (Milestone 4 — Runtime Governance & Observability)
- **Supersedes:** —
- **Extends:** ADR-0008 (telemetry is a derived plane)

## Context

Phases 4.1–4.5 built the telemetry the platform produces: a trace context, an
assembled span tree derived from domain rows (ADR-0008), governance decisions,
cost and budget data, and behavioral findings. All of it is readable through
this platform's own API. None of it is readable by the tools an enterprise
operations team already runs — Datadog, Azure Monitor, Grafana, Splunk, Elastic.

Making the platform interoperable with those tools raises three decisions, and
getting any of them wrong is expensive and hard to walk back.

1. **What does the platform depend on to speak their language?** Every one of
   those vendors ingests OpenTelemetry (OTLP). But "add the OpenTelemetry SDK"
   is a dependency on a large, fast-moving library with its own opinions, and
   "add the Datadog exporter" is worse — it is a dependency on one vendor, in
   the core of a platform an enterprise is evaluating partly *because* it does
   not want to be locked to one vendor.

2. **What happens to an agent execution when the collector is down?** The
   collector is an external system this platform does not control. It will be
   unreachable, slow, or returning 500s at some point. Everything else on the
   execution path fails closed — authorization denies, governance stops, a
   budget blocks (ADR-0009, ADR-0010). If export inherited that posture, a
   collector outage would stop agent executions.

3. **What bounds the memory the export path uses?** The obvious answer to (2) is
   "buffer the telemetry and retry when the collector recovers." Unbounded, that
   buffer is a slow out-of-memory: a collector down for an hour accumulates an
   hour of telemetry until the process dies — turning an *observability* outage
   into an *execution* outage, the exact thing (2) is trying to prevent.

ADR-0008 already anticipated this phase: its "Revisit when" section says *"An
OTel collector is introduced (4.6) … this ADR should state explicitly that the
exported copy is also derived."* This ADR is that statement, plus the two
decisions ADR-0008 did not cover (the adapter boundary and the fail-open
posture of export specifically).

## Options considered

### Decision 1 — the dependency boundary

#### Option A — a vendor-specific integration (e.g. the Datadog exporter) in core

- Pros: least code; the vendor's own library handles wire details and retries.
- Cons: **vendor lock-in in the core of an anti-lock-in product.** Switching to
  Grafana becomes a code change and a redeploy. The vendor's SDK is now on the
  platform's dependency-audit surface. An enterprise standardizing on a
  different tool cannot adopt the platform without us shipping a second
  integration.

#### Option B — the OpenTelemetry SDK imported directly wherever telemetry is produced

- Pros: standard; OTLP is vendor-neutral, so no *vendor* lock-in.
- Cons: the OTel SDK is now a hard dependency of `app/runtime` and
  `app/observability`. An SDK major version becomes a platform migration. The
  runtime code is coupled to a telemetry library's lifecycle for no runtime
  benefit. "Replaceable exporter" is a claim with nothing enforcing it.

#### Option C — the OTel SDK behind a single adapter package; core imports neither the SDK nor a vendor

- Pros: **the anti-lock-in guarantee becomes structural, not aspirational.**
  Core runtime code imports `app.telemetry_export`'s neutral interface (or
  nothing at all); only that package imports `opentelemetry`, and only its
  `sinks.py` touches the SDK. Swapping Datadog for Grafana is a config edit
  because there is no vendor name in the code to change. A test walks the AST
  of every other package and fails on a single `import opentelemetry`.
- Cons: an adapter layer is code to write and maintain; the neutral
  `ExportSpan` record is a third representation of a span (after the domain row
  and the assembled span). Mapping bugs are possible and must be tested against
  the real OTLP shape.

### Decision 2 — the failure posture of export

#### Option A — export participates in the execution transaction (fail-closed, for consistency)

- Pros: consistent with every other plane; a trace is never missing.
- Cons: **a collector outage stops agent executions.** Export is not the
  business transaction; making it gate execution is a category error. Rejected
  on the same reasoning ADR-0008 used for telemetry capture.

#### Option B — export is fail-open: an exporter failure never affects execution

- Pros: a collector outage is an observability event, not an execution event.
  The runtime is not even instrumented — a background dispatcher reads
  *already-terminal* executions and exports them after the fact, so there is no
  code path from an execution to an export to fail along.
- Cons: telemetry can be lost (a long outage past the buffer's bound drops the
  oldest spans). Exported data can lag the live system by a dispatch cycle. The
  "errors must still be visible" obligation has to be met some other way, since
  nothing throws.

### Decision 3 — buffering

#### Option A — unbounded in-memory retry queue

Never seriously in play. It is decision 2's failure mode reintroduced through
the back door: memory grows for the length of the outage until the process
OOMs.

#### Option B — bounded buffer, measured in spans, with a declared full-policy

- Pros: the worst case is a fixed amount of memory and a counted number of
  dropped spans, both observable. "Retry" means "retry next cycle, drop the
  oldest if producers have moved on" — bounded by construction.
- Cons: telemetry is dropped during a sustained outage. The drop policy
  (`drop_oldest` by default) is a choice that is right for incident response
  and wrong for anyone who wanted the *start* of an incident — they set
  `drop_newest`.

## Decision

**Decision 1: Option C.** The OpenTelemetry SDK lives behind
`app/telemetry_export`, a sibling package of `app/runtime` and
`app/observability`. Core runtime code imports no vendor SDK and no OTel SDK;
only `app/telemetry_export/sinks.py` imports `opentelemetry`, and it does so at
function scope. Exporters are a registry keyed on a transport string
(`otlp-http`, `null`), never a vendor name — vendors consume OTLP, they are not
switched between in code. A structural test (`test_ac02_*` in
`test_otel_interop.py`) walks the AST of every module outside the adapter and
fails on any vendor/OTel import.

**Decision 2: Option B.** Export is fail-open. It is not on the execution path
at all: `ExportDispatcher` reads executions that have already reached a terminal
state, assembles their traces through 4.2's existing read model, converts them
to neutral records, and hands them to a sink. Every public method catches
`Exception` and returns. An exporter failure is surfaced as **exporter-health
state** (`app/telemetry_export/health.py`) and a metric
(`act_telemetry_export_degraded`), never as an exception and never as an
execution error code. The §36 proof is a recorded test: a real execution
completes normally with the collector down, memory stays bounded, the errors
are visible, and the domain and audit records are untouched.

**Decision 3: Option B.** `BoundedSpanBuffer` has a hard maximum measured in
spans (the unit the "memory bounded" claim is about) and a declared policy when
full: `drop_oldest` (default), `drop_newest`, or `block_bounded` (wait a short,
fixed timeout, then drop). There is no "grow" option — `BUFFER_FULL_POLICIES`
does not contain one, and a test asserts that. The buffer lock is never held
across the network export, so a hung collector blocks only the dispatcher
thread.

**Extending ADR-0008:** the exported spans are also derived. They are produced
by `TraceAssembler` from the same domain rows, converted to OTLP, and sent. The
collector's copy is a downstream projection of the authoritative domain plane,
exactly as the platform's own trace view is. A disagreement between a Datadog
span and an `agent_executions` row is resolved in favour of the row. Export
changes where a derived view can be *read*; it does not add a plane.

## Consequences

### Positive

- An enterprise streams execution traces and operational metrics to any OTLP
  collector by pointing at an endpoint. No runtime change, no vendor lock-in,
  because there is no vendor in the code to lock to.
- A collector outage degrades observability and nothing else — proven by a test
  that runs a real execution with the collector down and asserts the execution
  row, the telemetry events, and the audit rows are all unchanged.
- Memory under a sustained outage is a fixed, configurable number of spans, and
  every dropped span is counted and visible on both the health endpoint and a
  metric.
- The planes stay distinct: export is fail-open telemetry; governance still
  fails closed (ADR-0009 unchanged); export is never an input to a governance
  decision.
- Swapping telemetry vendors is an operations task (edit an endpoint), not an
  engineering one.

### Negative / accepted cost

- **Telemetry is lost during a long outage.** Past the buffer's bound, the
  oldest (or newest) spans are dropped. This is the deliberate trade for
  bounded memory, and it means the exported stream must never be treated as
  complete — the same caveat ADR-0008 put on `runtime_events`.
- **Exported data lags the live system** by up to one dispatch cycle (default
  30s), because the dispatcher reads terminal executions rather than
  instrumenting live ones. An operator who needs sub-second freshness reads the
  platform's own trace API, not the collector.
- **A third span representation exists.** Domain row → `AssembledSpan` →
  `ExportSpan`. The mapping is a place bugs can live; it is tested by
  round-tripping through the real OTLP protobuf encoder and re-parsing the wire
  bytes.
- **The adapter is code to maintain.** An OTel SDK major bump still has to be
  absorbed — but in one package, behind one interface, with the blast radius
  visible in the import graph.
- **One dispatcher exports to one collector.** True per-environment fan-out
  (PRODUCTION → Datadog, STAGING → a local Grafana simultaneously) needs a
  dispatcher per environment, which this phase documents but does not build.
  The per-environment `telemetry_export` policy block selects *which* collector
  a process talks to; it does not multiplex.

### Residual risk

- The anti-lock-in boundary erodes the same way ADR-0008's does: not by someone
  adding a vendor SDK to core on purpose, but by a "quick" `import opentelemetry`
  in a runtime module to attach one attribute. The structural test is the guard,
  and it must not be weakened to `# noqa` a "temporary" exception.
- The fail-open property depends on the dispatcher staying off the execution
  path. A future phase that decides to instrument the live loop "for richer
  spans" would reintroduce exactly the coupling this ADR removed. That change
  should reopen this ADR, not slip through as an enhancement.
- `drop_oldest` is the default because incident response wants the most recent
  data. A deployment that cares about the *onset* of a slow degradation wants
  `drop_newest` and has to know to set it. This is documented in
  `docs/observability/opentelemetry.md`; it is still a footgun for anyone who
  does not read it.

## Revisit when

- **A tenant needs simultaneous multi-collector fan-out.** The current model is
  one dispatcher, one destination. Real per-environment or per-vendor fan-out
  needs either multiple dispatchers or a multiplexing sink, decided then with
  the concrete requirement in hand.
- **Metrics need to be push (OTLP) rather than scrape (Prometheus).** This phase
  scrapes metrics over `GET /metrics` and pushes only spans. A deployment whose
  collector cannot scrape (a push-only vendor gateway) would need an OTLP
  metrics exporter added behind the same adapter.
- **4.7 turns metrics into SLOs/alerts.** The alert lifecycle is explicitly out
  of scope here. When 4.7 builds it, it should confirm that an alert rule never
  becomes a governance input — the plane discipline this ADR relies on.
- **The OTel SDK ships a breaking major version.** The absorption happens in
  `app/telemetry_export/sinks.py`; if it ever cannot, that is a signal the
  adapter boundary is in the wrong place.
