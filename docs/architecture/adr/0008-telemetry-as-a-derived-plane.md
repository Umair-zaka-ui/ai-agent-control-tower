# ADR-0008 — Telemetry is a derived plane, never a source of truth

- **Status:** Accepted
- **Date:** 2026-08-25
- **Deciders:** Phase 4.1 (Milestone 4 — Runtime Governance & Observability)
- **Supersedes:** —

## Context

Milestone 4 adds observability to a platform that already has nine milestones of
authoritative state. Before writing any of it, there is a question that decides
the shape of everything after: **when the telemetry record and the domain record
disagree, which one is right?**

The forces:

1. **The domain plane already exists and is already authoritative.**
   `agent_executions`, `execution_attempts`, `execution_messages` and
   `tool_calls` record what actually happened, with timings, statuses, error
   classes, token counts and costs. Every one of them is written inside the
   transaction that made the thing true.

2. **Everything else in this codebase fails closed.** An authorization error
   denies. A policy error blocks. A release gate failure halts a rollout. A
   traffic-allocation gate with no servable version refuses the execution. That
   consistency is deliberate and it is the platform's main safety property.

3. **Observability systems are the least reliable component in most
   architectures.** They are the thing that fills a disk, exhausts a connection
   pool, or blocks on an unreachable collector. They are also, by design, in
   the path of everything.

4. **The obvious design duplicates the database.** A conventional tracing
   backend stores a span per operation. Applied here, that means a row per
   model call and per tool call — a second copy of `execution_messages` and
   `tool_calls`, differing only in schema.

5. **Measured state of the substrate.** `correlation_id` had existed on
   `agent_executions` since Milestone 1 and was null on 74,395 of 74,619 rows,
   because it was only ever read from the request body. `runtime_events` existed
   with ~297,000 rows, essentially all with a null correlation. So the choice
   was not "build telemetry or not" — it was "give the existing, unused
   substrate a contract, or build a parallel one beside it".

## Options considered

### Option A — Telemetry as an equal, independently-authoritative plane

Spans and events are first-class stored records. A trace backend owns its own
tables, written on the execution path, and queried directly for operations.

- Pros:
  - Conventional; matches how OpenTelemetry backends are usually deployed.
  - Queries are fast and self-contained — no joins across domain tables.
  - A span can carry attributes the domain row does not have.
- Cons:
  - **Two records of one fact.** A tool call would exist as both a `tool_calls`
    row and a span. They will disagree — after a partial failure, after a
    retry, after a schema change to one and not the other — and there is no
    principled way to decide which is right.
  - The write is on the execution path, so a telemetry write failure becomes an
    execution failure unless carefully isolated. The careful isolation is easy
    to get subtly wrong.
  - Storage grows as a multiple of the domain, for data that is a copy of it.

### Option B — Telemetry as a derived plane; spans assembled from domain rows

The domain rows *are* the trace. A span id is a pure function of (trace id, span
kind, row id). A trace is assembled by walking the foreign keys that already
exist. Telemetry storage holds only facts not derivable from the domain, and
telemetry writes are best-effort.

- Pros:
  - **One record of each fact**, so there is nothing to disagree.
  - Telemetry can be lossy without lying: a dropped event loses observability of
    a moment, never the record of what happened.
  - Historical data is covered for free — every execution ever recorded became
    traceable the moment the derivation existed, with no backfill.
  - The failure mode is bounded: the worst case is a gap in the event stream.
- Cons:
  - Assembling a trace costs joins, and will cost more as traces get read more.
  - A span cannot carry an attribute that is not on a domain row.
  - Attribution is limited by what the domain rows record — `tool_calls` has no
    `attempt_id`, so on a retried execution a tool call cannot be attributed to
    a specific attempt.

### Option C — Dual-write with reconciliation

Store spans, and reconcile against the domain periodically.

Never seriously in play. It accepts Option A's duplication *and* adds a
reconciliation process that must itself be correct, monitored and recovered —
paying twice to reach the consistency Option B has by construction.

## Decision

We chose **Option B**: telemetry is a derived plane, never a source of truth.

Concretely, three rules follow, and they are enforced in code rather than
documented and hoped for:

1. **The domain is authoritative.** Where telemetry and a domain row disagree,
   the row is right. `app/observability/` may read domain models; no runtime
   service depends on telemetry succeeding. The package is a *sibling* of
   `app/runtime`, so the dependency direction is visible in the import graph.

2. **Spans are derived, not stored.** `derive_span_id()` is a pure `uuid5` over
   (trace, kind, row, ordinal). `TraceAssembler` walks foreign keys and never
   writes. Phase 4.1 added two nullable columns and no table.

3. **Telemetry is non-gating.** `emit()` catches `Exception` *and* writes inside
   a `SAVEPOINT`. The savepoint is not belt-and-braces: without it a failed
   `INSERT` poisons the caller's transaction, so the swallowed exception
   resurfaces as a corrupted execution three frames up — correct-looking in a
   unit test, broken in production.

This is chosen against Option A specifically because of force (2). The rest of
this platform fails closed, and that is right — an authorization system that
fails open is not an authorization system. Telemetry is the one subsystem where
the inverse is correct, because **telemetry is not the business transaction**.
Making it fail closed for consistency's sake would convert every observability
outage into a production outage, which is precisely the failure mode force (3)
warns about.

## Consequences

### Positive

- There is exactly one answer to "what happened", and it is the one written in
  the transaction that made it happen.
- An observability failure degrades observability and nothing else. Proven by a
  test that runs a real execution with the emitter monkeypatched to raise.
- Every historical execution is traceable with no migration writing to it:
  `trace_id_for()` falls back to the primary key, so ~74,000 pre-existing rows
  gained a stable trace identity at zero cost and with nothing to reverse.
- Telemetry storage grows with *events*, not with a copy of the domain.
- Recomputing a trace is deterministic, so a stored `span_id` reference stays
  valid without the span ever having been written down.

### Negative / accepted cost

- **Reading a trace costs joins.** Assembling one execution reads four tables.
  This is fine at one trace at a time and will not be fine for a list view over
  thousands; Phase 4.2 will need either an index or a projection, and it will
  have to justify it.
- **A span can only carry what a domain row carries.** Adding a span attribute
  means adding a column to the row that owns the fact. That is usually the right
  place for it, but it makes some attributes more expensive to add than they
  would be in a free-form span store.
- **Attribution gaps are visible rather than papered over.** On a retried
  execution, tool spans attach to the execution root instead of an attempt,
  because the data does not support attributing them. The assembler says so in
  its `notes`. A stored-span design would have recorded the attempt at write
  time and not had this gap.
- **Events can be lost.** That is the deliberate trade, but it means the event
  stream must never be used for anything that requires completeness — billing,
  compliance, or an audit trail. Those belong to the domain and audit planes.

### Residual risk

- The most likely way this decision erodes is **not** by someone adding a span
  table on purpose. It is by a later phase adding "just one" denormalized
  `correlation_id` to a child table for query convenience, then another, until
  the domain rows carry a shadow copy of the trace. The guard against that is
  the test asserting 4.1's migration adds no table — which would not catch a
  column added by 4.5. This needs watching at review time, not in CI.
- The non-gating property depends on the SAVEPOINT staying in place. A future
  refactor that "simplifies" `emit()` by removing `begin_nested()` would keep
  every test passing except the one that asserts the session is usable after a
  failure. That test is the load-bearing one and should not be deleted.

## Measurement outcome (Phase 4.2, 2026-08-26)

> This ADR said: *"Phase 4.2 measures trace-list latency. If assembling traces
> for a list view exceeds the budget, the answer is a read projection or an
> index, decided there with real numbers — not a span table added on suspicion."*
> It was measured. **No projection was added. One index was.**

### What was measured

Against the live development database at **90,695 executions / 355,377
runtime_events**, warm, 40 iterations per shape:

| Query | p50 | p95 | Seq scan? |
|---|---|---|---|
| Explorer list (tenant + recency + LIMIT 50) | 0.53ms | 0.65ms | No |
| Explorer, filtered (status + 30-day window) | 0.51ms | 0.63ms | No |
| Explorer, lookup by trace id | 0.15ms | 0.26ms | No |
| **Trace-detail assembly** (4-table walk) | **0.74ms** | **1.08ms** | No |
| Trace events for an execution | 0.14ms | 0.15ms | No |

Every explorer filter dimension, measured separately:

| Filter | p50 | Filter | p50 |
|---|---|---|---|
| base (tenant + recency) | 0.23ms | model (join version JSONB) | 0.49ms |
| status | 0.24ms | tool (EXISTS on `tool_calls`) | 0.87ms |
| environment (join deployment) | 0.36ms | error class | 0.30ms |

### The decision: assembly stands, no materialization

Trace assembly runs three orders of magnitude inside any reasonable budget.
Every child table (`execution_attempts`, `execution_messages`, `tool_calls`,
`runtime_approvals`) already carries an `execution_id` index, so the walk is
index-backed end to end and costs a fixed number of queries regardless of how
many spans a trace contains.

**A read projection would have optimized a query that costs less than a
millisecond**, at the price of a second copy of the data to keep in sync — the
exact §13 duplication this ADR rejected, reintroduced for no measured gain. So
none was added, and the numbers above are recorded so the restraint is
falsifiable rather than merely asserted.

### What the measurement also found, which mattered more

The dev data is fragmented across **62,126 organizations**, so the busiest
tenant owns only 500 executions. That made every tenant-scoped query look fast
for a reason that would not hold for a real customer — a benchmark that
confirms what you hoped is worth less than one that surprises you, so the honest
worst case was measured too: *one tenant owning the whole table*.

| Worst-case shape | p50 | p95 | Plan |
|---|---|---|---|
| all-rows recency LIMIT 50 | 26.94ms | 142.27ms | **Parallel Seq Scan** |
| all-rows + status filter | 24.83ms | 136.99ms | **Parallel Seq Scan** |
| all-rows 30-day window | 28.64ms | 133.77ms | **Parallel Seq Scan** |

`agent_executions` had **no index on `created_at` at all** — not standalone, not
composite. The explorer's default query therefore planned as a bitmap scan over
every row a tenant owns, followed by a top-N sort. At 500 rows that is 0.2ms and
invisible; at 500,000 it is the whole table.

**Migration 0046** adds `(organization_id, created_at DESC)`. Before and after,
same query, same tenant:

```
BEFORE   Bitmap Heap Scan -> rows=500 -> top-N heapsort    18 buffers   0.196ms
AFTER    Index Scan       -> rows=50  -> (no Sort node)     4 buffers   0.043ms
```

The disappearing `Sort` node is the point, far more than the 0.15ms. Bitmap plus
sort is **O(rows the tenant owns)**; an index walked in `created_at DESC` order
and stopped at the LIMIT is **O(limit)** — flat as a tenant grows.

**This is not a §13 duplication and does not weaken this ADR.** An index stores
no independent copy of anything: it contains only values already in the table's
own columns, Postgres maintains it, and nothing reads it as a source of truth
because it is not a source of anything. It is an access path to the
authoritative table. The distinction that matters is between *a faster route to
the truth* (an index) and *a second thing that claims to be the truth* (a
projection). This ADR forbids the second, not the first.

### Why no further indexes

Every filtered variant lands between 0.24ms and 0.87ms once the tenant+recency
index does the narrowing. A composite index per filter combination would be
speculative bloat — write amplification on the hottest table in the system, paid
on every execution insert, to speed up reads that are already sub-millisecond.
If a combination later proves slow at real volume, it earns its own index then,
with its own numbers.

### Where this is now checked

The measurement is a **recorded test** (`test_ac07_adr0008_*` in
`backend/tests/runtime/test_execution_tracing.py`), not a note in a commit
message, so "assembly is fast enough" keeps being checked rather than having
been true once. A companion test asserts the plan reaches its rows through
`ix_agent_executions_org_created` and never sequentially scans, and a second
asserts the sort elision at volume against the busiest tenant present.

One nuance found while writing those tests and worth stating, because it looks
like a failure and is not: for a tenant owning almost nothing, Postgres
correctly prefers a bitmap index scan plus a trivial sort over an ordered
traversal — sorting fourteen estimated rows is cheaper than walking the index in
order. Asserting "no Sort" unconditionally would demand a *worse* plan for the
small-tenant case. The sort elision is a property at volume, and it is tested
there.

## Revisit when

- ~~**Phase 4.2 measures trace-list latency.**~~ **Done — see "Measurement
  outcome" above.** Assembly measured 0.74ms p50 at 90,695 executions, so no
  projection was added; the measurement did expose a missing `created_at` index,
  fixed by migration 0046. The next trigger is below.
- ~~**An OTel collector is introduced (4.6).**~~ **Done — see
  [ADR-0011](./0011-opentelemetry-export-as-a-fail-open-plane.md).** Phase 4.6
  added OTLP export behind an adapter. It does not change which plane is
  authoritative: the exported spans are produced by the same `TraceAssembler`
  from the same domain rows and are a downstream projection, exactly as the
  platform's own trace view is. A disagreement between a collector's span and an
  `agent_executions` row is resolved in favour of the row. ADR-0011 also draws
  the fail-open line for export *specifically* (an exporter outage never affects
  an execution) and the bounded-buffer rule (retry is never an unbounded queue).
- **Anything requires event completeness.** If a later requirement needs a
  guaranteed-complete event stream (a billing feed, a regulatory report), it
  must not be built on `runtime_events`. That requirement should reopen this
  ADR rather than quietly make telemetry non-lossy.
