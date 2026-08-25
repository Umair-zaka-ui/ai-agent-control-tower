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

## Revisit when

- **Phase 4.2 measures trace-list latency.** If assembling traces for a list
  view exceeds the budget, the answer is a read projection or an index, decided
  there with real numbers — not a span table added on suspicion.
- **An OTel collector is introduced (4.6).** Exporting to an external backend
  means spans exist outside this database. That does not change which plane is
  authoritative, but it does mean this ADR should state explicitly that the
  exported copy is also derived.
- **Anything requires event completeness.** If a later requirement needs a
  guaranteed-complete event stream (a billing feed, a regulatory report), it
  must not be built on `runtime_events`. That requirement should reopen this
  ADR rather than quietly make telemetry non-lossy.
