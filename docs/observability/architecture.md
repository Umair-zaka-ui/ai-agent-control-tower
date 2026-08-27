# Observability architecture — the three-plane model

> **Phase 4.1 (ACT-SRS-M4).** This document describes the instrumentation
> foundation Milestone 4 stands on: what the planes are, why telemetry is
> allowed to fail, how a trace is put together, and what this phase deliberately
> did not build.

## The three planes

The single most important thing to understand about telemetry in this platform
is that it is **not** the record of what happened. It is a *view* of the record.

| Plane | Where it lives | Authoritative? | May it lose data? |
|---|---|---|---|
| **Domain** | `agent_executions`, `execution_attempts`, `execution_messages`, `tool_calls`, … | **Yes** — this is what happened | No |
| **Audit** | `authorization_audit` | Yes, for "who was allowed to do what" | No — compliance record |
| **Telemetry** | `runtime_events`, plus derived traces | **No** — derived from the domain | **Yes, deliberately** |

When the telemetry plane and a domain row disagree, the row is right. The
reasoning, the options rejected and the costs accepted are recorded in
[ADR-0008](../architecture/adr/0008-telemetry-as-a-derived-plane.md); this
document describes the result.

The planes are separated in the import graph, not only on paper.
`app/observability/` is a **sibling** of `app/runtime/` and `app/integration/`,
for the same reason `app/integration/` is a sibling rather than a child: the
dependency runs one way. The runtime may call into observability best-effort;
nothing in observability calls back into a runtime service.

```
app/
├── runtime/         # the domain. authoritative.
├── integration/     # connectors. the runtime never knows about these.
└── observability/   # derived. reads the domain, is read by nobody in it.
```

## Telemetry is non-gating, and it is the only thing here that is

Everything else in this codebase **fails closed**. An authorization error
denies. A policy error blocks. A release gate failure halts a rollout. A traffic
allocation with no servable version refuses the execution outright.

Telemetry is the deliberate inverse (SRS §9). **A telemetry failure is never an
execution failure.** An execution that ran correctly but whose telemetry write
failed is a successful execution with missing telemetry, and any other reading of
it turns the observability layer into a new way for production to break.

This is enforced two ways in `app/observability/events.py`, and **both are
necessary**:

```python
try:
    with db.begin_nested():        # (2) SAVEPOINT
        db.add(RuntimeEvent(...))
    return True
except Exception:                  # (1) never propagate
    logger.warning(...)
    return False
```

The `try/except` is the obvious half and on its own it is **not enough**. A
failed `INSERT` leaves the surrounding transaction in a failed state, so the
*caller's* next statement raises — meaning the exception swallowed here
resurfaces as a corrupted execution three frames up. That bug looks correct in a
unit test and fails in production. The SAVEPOINT is what makes the guarantee
real, and the test that pins it asserts the session is still usable after a
forced failure:

```python
assert emit(db_session, record) is False
assert db_session.execute(text("SELECT 1")).scalar() == 1   # the whole point
```

The emitter also **does not commit**. The row joins the caller's transaction and
lands when the caller commits, so telemetry never introduces a second commit
point into an execution.

## How a trace is put together

**One execution is one trace**, identified by `correlation_id`.

### Trace identity

```python
def trace_id_for(execution):
    return execution.correlation_id or str(execution.id)
```

That fallback is why Phase 4.1 needed no data backfill. When this phase started,
**74,395 of 74,619** executions had a null `correlation_id` — the column had
existed since Milestone 1 and nothing populated it. Backfilling would have been
74,000 one-way writes that a downgrade could not reverse. The derivation gives
every one of those rows a stable, unique trace identity for free.

It is also not a degraded mode. An execution that was never part of a wider
caller-defined trace genuinely *is* its own trace, and its primary key is the
correct name for that trace.

### Spans are derived, never stored

A span id is a pure function:

```python
derive_span_id(trace_id, kind, row_id, ordinal)  # uuid5, deterministic
```

Same inputs, same id, forever, with nothing persisted. Assemble a trace twice and
the span ids are byte-identical — which is what makes storing them unnecessary,
and what keeps a stored `runtime_events.span_id` reference valid without a span
table existing.

The span tree mirrors the domain structure, because **the domain structure
already is the trace**:

| Span kind | Backed by |
|---|---|
| `execution` | `agent_executions` (root) |
| `authorization` | a phase, not a row — no table of its own |
| `runtime_policy` | a phase (Phase 4.2) |
| `queue` | a computed gap, `queued_at`→`started_at` (Phase 4.2) |
| `approval` | `runtime_approvals` (Phase 4.2) |
| `attempt` | `execution_attempts` |
| `model_call` | the `assistant` row in `execution_messages` for that iteration |
| `tool_call` | `tool_calls` |
| `external_call` | the HTTP columns on `tool_calls` |
| `scheduled_job` | `job_runs` |

That hierarchy was built for execution, not for observability, and it happens to
be exactly the parent linkage a trace needs. Recognizing that is what let this
phase add **two columns instead of two tables**.

### One honest limitation

`tool_calls` records `loop_iteration` but not `attempt_id`. So on a **retried**
execution, a tool call cannot be attributed to a specific attempt from the data
alone. Rather than guess, tool spans on a multi-attempt execution attach to the
execution root, and the assembled trace says so in its `notes` field.

Attaching them to the latest attempt would be right most of the time and
silently wrong exactly when someone is debugging a retry — the only time anyone
reads a trace this closely.

## Correlation propagation, leg by leg

This is what Phase 4.1 actually fixed. The state it found:

| Leg | Before 4.1 | After |
|---|---|---|
| HTTP → execution | **Broken.** `correlation_id` read *only* from the request body; `POST /executions` took no `Request` object, so no header could reach it | `TraceContext.from_headers()` reads `x-correlation-id` / `x-request-id`, and mints a trace id if neither is present |
| execution → queue | Intact by construction — the id is on the row | unchanged |
| queue → worker | Intact by construction — the worker reads the row it claimed | unchanged |
| worker → model/tool | **Structural** — `execution_messages` and `tool_calls` both carry `execution_id` | unchanged; deliberately *not* denormalized |
| execution → `runtime_events` | **Broken.** `_record_event` never set `correlation_id`; ~297,000 rows, essentially all null | every event now carries the trace identity and a span id |
| scheduler | No trace identity | `TraceContext.for_job_run()` derives it from the row id |

### The worker leg needs no mechanism at all

A worker does not *receive* a `TraceContext`. It **reconstructs** one from the
execution row it claimed:

```python
claimed = session.get(AgentExecution, execution_id)
trace = TraceContext.for_execution(claimed)      # identical to the HTTP leg's
```

So the trace crosses a process boundary with no message payload, no header
forwarding and no shared memory — because the trace id was written to the row
the worker just read. Propagation across the queue therefore costs nothing and
cannot fail (SRS §9, §25): there is no serialization step to get wrong and no
round trip on the hot path.

### The scheduler leg

A scheduled occurrence has no caller and therefore no inbound correlation
header, so its trace identity is derived from its own `job_runs` row:

```python
TraceContext.for_job_run(run)      # trace_id == str(run.id)
```

That is enough, and it needs no schema change, because **a retry and a
lease recovery both reuse the same `job_runs` row** — which is what makes
exactly-once structural in Phase 3.8. So one occurrence has one row, one row
has one trace, and every event it emits across every attempt belongs to it.

This had to be *wired*, not merely made available. `SchedulerService._audit`
already routed through `_record_event`, so before this each of an occurrence's
events was getting a freshly minted trace id — a run's `STARTED` and its
`SUCCEEDED`/`FAILED` belonged to different traces, leaving the run
unreconstructable. That is the same failure this phase exists to fix, arriving
through a different door.

### Precedence, and the subtle regression it avoids

```
explicit payload["correlation_id"]  →  x-correlation-id header  →  minted uuid4
```

The explicit body field wins because a caller that names its own correlation
means it.

**The minted id reaches the execution row and never the payload**, and that is
load-bearing. Phase 3.4 uses `payload["correlation_id"]` as its sticky
version-routing key. Had the auto-minted correlation been written into the
payload, every request would silently have become sticky — quietly defeating
percentage rollouts for a small user base. `_routing_key` still reads exactly
what it read before this phase, and a test pins that.

## What the hot path costs

Capture must not introduce a lock or a synchronous wait on the execution path
(SRS §25), and must never hold a lock across model or tool I/O — the standing M1
deadlock discipline (see [workers-and-queue](../runtime/workers-and-queue.md)).

- **Context propagation**: zero database access. `app/observability/trace.py`
  imports no SQLAlchemy at all, asserted over the AST.
- **Event emission**: one local `INSERT` inside a SAVEPOINT. No lock taken, no
  commit, nothing held across I/O.
- **Trace assembly**: read-only, and never on the execution path — it runs when
  someone asks for a trace.

## The one HTTP surface

```
GET /api/v1/runtime/executions/{execution_id}/trace
```

Permission: `runtime.telemetry.view` — which already existed, and whose
description already read *"View runtime telemetry and execution traces"*.

Phase 4.1 is instrumentation, not an API; the trace explorer is 4.2. This
endpoint exists because "traces assemble from existing rows without a span
table" is a claim that deserves to be verifiable against a real execution rather
than only in a unit test. It returns metadata only, and it is tenant-scoped —
another tenant's execution is indistinguishable from one that does not exist.

> **Superseded surface (Phase 4.2).** The canonical trace API is now
> `/api/v1/observability/` — see [tracing.md](./tracing.md). This 4.1 route is
> retained and delegates to the same assembler, so the two cannot diverge, but
> new callers should use the observability prefix.

## What Phase 4.1 deliberately did not build

**Since shipped:**

- ~~The trace explorer and timeline UI (4.2).~~ The explorer and full trace
  assembly shipped in **Phase 4.2** — see [tracing.md](./tracing.md). Its *UI*
  is still deferred, to the observability center (4.9).
- ~~The governance enforcement engine (4.3).~~ Shipped in **Phase 4.3**, and it
  is the deliberate **inverse of this plane**: governance fails *closed* where
  telemetry fails *open*, and the two now live inches apart inside the same
  loop. A telemetry failure never changes a governance decision, and the
  governance engine never reads this plane. See
  [../runtime/runtime-governance.md](../runtime/runtime-governance.md) and
  [ADR-0009](../architecture/adr/0009-runtime-governance-as-a-fail-closed-plane.md).

**Still out of scope:** cost governance (4.4), behavioral signals (4.5),
OpenTelemetry export (4.6), SLOs and alerting (4.7), the full telemetry policy /
retention / access system (4.8 — only the METADATA_ONLY baseline and the
scrubber land here), the observability center (4.9), and hardening (4.10).

It also changed no execution behaviour and duplicated no domain data. Every
later M4 phase builds on this contract.

## See also

- [semantic-conventions.md](./semantic-conventions.md) — the attribute
  vocabulary and the bounded-cardinality rule
- [tracing.md](./tracing.md) — the assembly walk, the explorer, and the
  metadata/content boundary (Phase 4.2)
- [privacy.md](./privacy.md) — the scrubber, METADATA_ONLY, and the
  no-chain-of-thought rule
- [ADR-0008](../architecture/adr/0008-telemetry-as-a-derived-plane.md) — why
  telemetry is derived
