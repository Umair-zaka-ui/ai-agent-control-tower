# Execution tracing — the assembly walk, the explorer, and the content line

> **Phase 4.2 (ACT-SRS-M4 §6, §13, §15, §26, §28, §34).** How a trace is
> reconstructed, how to find the one you want, and what it deliberately will not
> show you. Builds directly on 4.1's rails — see
> [architecture.md](./architecture.md) for the three-plane model.

## The one-paragraph version

A trace is **not stored**. It is reconstructed on demand by walking the foreign
keys that already exist between `agent_executions` and its children, over the
`correlation_id` rails Phase 4.1 established. Span ids are a deterministic
`uuid5`, so two assemblies of one execution produce byte-identical results
without anything having been written down. Phase 4.2 measured this at real
volume and it costs **0.74ms p50** — so no projection was added, and the numbers
are recorded in [ADR-0008](../architecture/adr/0008-telemetry-as-a-derived-plane.md).

## The assembly walk

| Node kind | Backed by | Row or computed? |
|---|---|---|
| `execution` | `agent_executions` | **Row** (the root) |
| `authorization` | — | **Computed phase** |
| `runtime_policy` | — | **Computed phase** |
| `queue` | — | **Computed gap** |
| `approval` | `runtime_approvals` | **Row** |
| `attempt` | `execution_attempts` | **Row** |
| `model_call` | `execution_messages` (the `assistant` row per turn) | **Row** |
| `tool_call` | `tool_calls` | **Row** |
| `external_call` | `tool_calls` HTTP columns | **Row** |
| `finalization` | — | **Computed phase** |

Six of the ten are backed by a real row and say which one — every span carries
`source_table` and `source_id`, which is the proof it is a *view* of an
authoritative record rather than a copy of it. The other four are computed, and
report `source_table: null` so a reader can tell the difference at a glance.

### Why the computed ones are worth having

**`queue` is a gap, not a row.** Nothing in this schema records "the queue" as
an entity and 4.1 deliberately added no table for one. But `queued_at` →
`started_at` is a real, externally-meaningful interval, and in a slow trace it is
frequently the largest one: an operator asking *"why did this take 40 seconds?"*
is usually looking at queue wait, not model latency. Omitting it because no row
exists would hide the answer to the most common question a trace is opened to
answer.

It is emitted **only when both ends are known**. An execution still waiting has
an open-ended wait, not a measured duration, and reporting one would
misrepresent live state.

**`authorization` and `runtime_policy` are distinct phases**, not one gate. They
answer different questions and fail with different codes: *"may this
principal?"* versus *"does this request violate a runtime rule?"*. What makes
them derivable at all is that each has a distinct terminal signature on the
execution — a `DENIED` status with `RUNTIME_POLICY_DENIED`, or `BLOCKED` with the
policy's own code. An execution that passed both leaves no denial marker, which
is exactly how a passing gate is recognized.

The policy node is **not emitted for a `DENIED` execution**, because the policy
gate only runs if authorization allowed. Showing it would display a phase that
never executed.

**`finalization` is omitted while the execution is running.** A node claiming a
terminal status on a live execution is precisely the torn read that would
misrepresent state.

### The root is an envelope

The root `execution` span starts at `created_at` and ends at `completed_at`, so
every node sits inside it. This was a real modelling bug inherited from 4.1,
found when 4.2 added the gate nodes: the root previously started at `started_at`,
which put the authorization and queue nodes *before their own parent* — incoherent
on a timeline. Spans are returned root-first, then chronologically, with
unknown-start nodes last.

### One honest limitation

`tool_calls` records `loop_iteration` but not `attempt_id`. On a **retried**
execution a tool call cannot be attributed to a specific attempt from the data
alone, so tool spans on a multi-attempt execution attach to the execution root
and the trace says so in its `notes`. Attaching them to the latest attempt would
be right most of the time and silently wrong exactly when someone is debugging a
retry — the only time anyone reads a trace this closely.

## The governing decision

Where the domain already recorded *why* something was refused, the node shows it:
`decision`, `error_code`, the platform's own templated `reason`, and
`risk_score`. Phase 4.3 will author richer governance decisions; **4.2 authors
none** — it displays what already exists.

The `reason` is included as metadata rather than content because it is a
templated explanation this codebase writes (a concurrency cap, a cost budget),
never a model output or user input.

## The explorer

```
GET /api/v1/observability/traces
```

Filters: `trace_id`, `execution_id`, `agent_id`, `agent_version_id`,
`deployment_id`, `environment`, `model`, `provider`, `tool_id`, `status`,
`error_code`, `only_errors`, `started_after`, `started_before`.

Three of those are not columns on `agent_executions` — `environment` lives on the
deployment, `model`/`provider` in the version's `model_configuration` JSONB, and
`tool_id` on `tool_calls`. Each is compiled as a **correlated `EXISTS`, not a
join**: a join would multiply rows when the child side is not unique (a tool
filter returning one row per matching tool call) and then need a `DISTINCT`,
which reintroduces the very sort migration 0046 exists to remove.

### Bounded on three axes

Any one of these alone leaves a shape that is cheap on a small tenant and a table
scan on a large one, so all three apply at once:

1. **Tenant predicate leads every plan.** There is no code path in the explorer
   that builds a statement without an `organization_id` filter — asserted
   structurally over the AST.
2. **Pagination**, capped at `MAX_PAGE_SIZE` (200). The route bounds it at the
   schema and the service clamps independently, so an internal caller cannot
   bypass it.
3. **A default 30-day window.** An absent time range does not mean "everything".
   A caller who genuinely wants a wider window must ask for it and say so.

`has_more` is derived by fetching one row past the page rather than issuing a
`COUNT(*)` — a count over a large tenant costs a full index traversal to produce
a number the UI renders as "1,000+" anyway.

### Trace id resolution

A trace id is either a caller-supplied `correlation_id` — which may legitimately
span several executions, so `GET /traces/{id}` returns a list — or an
execution's own primary key, used as 4.1's derived fallback. Correlation is
tried first, because it is the caller's own intent while the id is our inference.

An execution that *has* a correlation does not also answer to its primary key;
otherwise one execution would have two trace identities.

## Tenant isolation (§34)

The requirement is not merely refusing to read another tenant's data — it is
refusing to **confirm it exists**. Both the correlation lookup and the id lookup
apply the tenant predicate, so a cross-tenant trace id and a nonexistent one
produce identical responses (asserted on the error payload; only the envelope's
per-request id and timestamp differ). Resolving the id branch without the tenant
filter would let one tenant confirm another's execution id by observing the
difference between a 404 and an empty list.

## The content line — metadata now, content in 4.8

**This is the hard boundary of the phase.** A trace shows timings, statuses,
resource identities, error classes, cost, token counts, which tool, which model,
which decision. It does **not** show prompt text, tool arguments or results, or
model output.

Enforced upstream of the routes: neither the assembler nor the explorer reads a
content column at all, asserted over the AST as attribute reads. So the boundary
cannot be undone by a route change alone.

`runtime.trace.content.view` is **named in code and deliberately not registered**
in the permission catalog. Naming it gives the boundary a visible owner;
registering it would create a grantable permission that guards nothing, which
teaches operators it is safe to grant — the same reasoning 4.1 used.

## Permissions

Reads require `runtime.telemetry.view`, which already existed and whose catalog
description already read *"View runtime telemetry and execution traces"*. Phase
4.2 registered no synonym: two permission codes guarding one capability is how an
authorization model drifts from what operators believe they granted. (The build
prompt suggested `runtime.observability.view`; the deviation and its reasoning
are recorded in this phase's report and in `REPO_STATE.md`.)

## Routes

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/observability/traces` | Explorer — filter, search, paginate |
| GET | `/api/v1/observability/traces/{trace_id}` | One trace by trace id |
| GET | `/api/v1/observability/executions/{id}/trace` | One execution's trace (canonical) |

Phase 4.1's `/api/v1/runtime/executions/{id}/trace` is retained and delegates to
the same assembler, so the two cannot diverge. New callers should use the
observability prefix.

This surface is distinct from the legacy `analytics` dashboards, which aggregate
the Phase 3 `agent_actions` table with flat cost estimates and have no connection
to `AgentExecution` at all. No path collision.

## Non-gating

Trace reads are ordinary indexed reads. They take no lock, write nothing, and
cannot affect the execution they describe — including one still in flight
(SRS §9). A test reads a trace repeatedly and asserts the execution's status,
`updated_at`, cost and attempt count are byte-identical afterwards.

## See also

- [architecture.md](./architecture.md) — the three-plane model, non-gating telemetry
- [privacy.md](./privacy.md) — the scrubber, METADATA_ONLY, no chain-of-thought
- [ADR-0008](../architecture/adr/0008-telemetry-as-a-derived-plane.md) — the
  derived-plane decision **and its Phase 4.2 measurement outcome**
