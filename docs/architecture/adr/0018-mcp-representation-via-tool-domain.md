# ADR-0018 — An MCP server is represented via the existing Tool domain, not a second tool registry

- **Status:** Accepted
- **Date:** 2026-09-09
- **Deciders:** Phase 5.4 / M5.4 (Milestone 5 — Universal Agent Control & Security Fabric)
- **Supersedes:** —
- **Relates to:** ADR-0002 (PostgreSQL as the sole datastore), ADR-0008
  (telemetry as a derived plane — the assemble-from-rows discipline reused
  for blast-radius), ADR-0017 (the relational control graph — this ADR is
  its Phase 5.4 confirmation: "confirm the one-table + recursive-CTE design
  still holds with dependency edges … and run the graph-at-scale benchmark
  deferred here").

## Context

Milestone 5.4 turns the control graph into a **security** capability. It
extends the Phase 5.3 substrate (`control_graph_edges` + recursive-CTE
traversal) with **dependency edges** — agent→tool, agent→credential,
agent→MCP-server, MCP→tool, tool→credential, tool→resource,
credential→resource — and delivers the **blast-radius queries** the
milestone points at: *which agents can reach payroll · what breaks if this
credential is revoked · which agents depend on this MCP server · which
agents can reach a resource of kind K.*

The phase makes **MCP a first-class, security-relevant dependency surface**.
The reflexive move is to build an MCP tool registry: a table of MCP servers,
a table of the tools each exposes, an MCP-specific invocation path. That
would fork the tool domain in three places that must never diverge:

1. **Schema validation.** M1 validates every tool call's arguments against a
   declared JSON-Schema input contract before anything with a side effect
   runs. A second tool table would need its own copy — and a *tool-poisoning*
   attack (a manipulated tool schema/description) is exactly what that
   validation is supposed to catch.
2. **The tool gateway.** M1 routes every tool invocation through one gateway
   (egress/SSRF guard, concurrency ceiling, retry/circuit-breaker, per-call
   audit). A second registry means a second gateway, or an un-governed path.
3. **Governance.** Capability grants, `agent_tools` assignments, risk levels,
   approval gates — all keyed on `tools.id`.

A second MCP tool universe would mean an MCP-exposed tool is governed,
validated and contained *differently* from a native tool. SRS §2.4 forbids
exactly this.

There is also no models registry to point an `agent→model` edge at (a model
is a `{provider, model}` string on `agent_versions.model_configuration`), so
that edge type is deliberately **not** in the vocabulary — the model-provider
dependency surfaces as `agent → credential` against the `provider_credentials`
row, the same restraint 5.3 applied to `AGENT_DELEGATES_TO`.

## Decision

**An MCP server is represented *via* the existing `Tool` domain. One tool
registry, one schema-validation path, one gateway. No graph database, no
materialised projection — the §V benchmark confirmed assembly from edges is
fast enough.**

1. **`mcp_servers` is a NEW table, but it holds no tools.** It carries an MCP
   server's *identity, provenance, ownership, trust/approval state, version
   and endpoint reference* — and nothing about the tools it exposes. No
   existing table represents "an MCP server, with a trust state, that
   provides tools": `provider_credentials` is about model providers,
   `connectors` about the integration framework. So the table is new; but it
   is not a tool table.

2. **The tools an MCP server exposes are ordinary `tools` rows.** They are
   created through the existing runtime tool API, validated by the existing
   schema validation, invoked through the existing gateway. The only link is
   **one additive nullable column, `tools.mcp_server_id`** — a native tool
   leaves it `NULL`, an MCP-exposed tool points it at its server. This is the
   "additive MCP-via-Tool link, justified" that AC-15 permits.

3. **The agent↔MCP and MCP↔tool relationships are dependency *edges*** on
   `control_graph_edges` (`DEPENDS_ON_MCP_SERVER`, `MCP_EXPOSES_TOOL`) — more
   `edge_type` values on the 5.3 table, no new edge table (ADR-0017 point 3).

4. **Dependency edges reference existing rows and grant no authority.** Each
   carries `evidence.mode` ∈ `{OBSERVED, DECLARED}` — an *observed* dependency
   (a `tool_calls` row: this agent invoked this tool) is different evidence
   from a *declared* one (an `agent_tools` binding, a `tool_credentials` row).
   Reading a dependency or a blast radius grants nothing;
   `AuthorizationGateway` stays the sole decider.

5. **MCP trust/approval state is surfaced as evidence, not enforced.** A
   server's `trust_status` other than `APPROVED` (`PENDING`, `UNKNOWN`,
   `REJECTED`) makes an agent's dependency on it *visible and flaggable*
   (`GET /graph/blast-radius/unapproved-mcp`). Unknown ≠ safe. The posture
   *finding* is Phase 5.5's job; 5.4 surfaces the evidence.

6. **Blast-radius reuses the 5.3 recursive-CTE machinery.**
   `traverse_with_edges` is `traverse` plus an accumulated edge-id array
   hydrated into an explainable path — same per-hop `organization_id = :org`
   bound, same path-array cycle guard, same `MAX_TRAVERSAL_DEPTH = 32` cap,
   same out-of-tenant truncation. No new traversal engine.

7. **No materialised projection.** The §V benchmark (below) measured
   blast-radius assembly at a single-busy-tenant worst-case well under 1s, so
   the "no projection" call from ADR-0017 holds — now backed by a real
   measurement at scale, which is exactly what ADR-0017 asked Phase 5.4 to
   produce. A projection is added *only* if a future measurement proves
   assembly too slow, and then as its own ADR.

### The §V graph-at-scale benchmark

Fixture: one tenant, a sparse dependency graph of realistic shape (≈12,000
agents → ≈10 tools each; tools → resources; tools → credentials),
`ANALYZE`d (a bulk load leaves stale planner statistics that autovacuum
maintains in production), ≈128,000 dependency edges.

| Query | Latency |
| --- | --- |
| which agents can reach the payroll resource | ~270 ms |
| what breaks if a busy credential is revoked | ~110 ms |
| which agents reach a resource of kind `payroll` | ~130 ms |
| agents depending on an unapproved MCP server | ~40 ms |

Extrapolation to the 1M-edge target: the traversal is an index scan on
`ix_control_graph_edges_target` per hop (`Index Cond: organization_id =
… AND target_type = … AND target_id = …`), bounded by `MAX_TRAVERSAL_DEPTH`
and the path-array cycle guard; cost scales with the *reachable* set for a
given start node, not total edge count. ADR-0017 already recorded M4 running
bounded recursive queries at ~109k rows sub-millisecond. The stale-statistics
cliff (a cold bulk load planned as if the table were tiny — ~20 s) is a
planner-stats artefact, not an algorithmic one, and does not occur under
autovacuum-maintained statistics.

**Decision: no projection. The numbers are recorded here and in
`test_ac08_v_blast_radius_benchmark_at_scale`.**

## Consequences

### Positive
- An MCP-exposed tool and a native tool share one registry, one schema
  validation, one gateway, one governance model. Tool poisoning is caught by
  the same validation whether the tool is native or MCP-exposed.
- The dependency graph is more `edge_type` values on the 5.3 table — no new
  table, no migration to a graph store, no second traversal engine.
- Blast-radius answers are deterministic, explainable (each names its edge
  chain + evidence) and per-hop tenant-bounded, re-proven adversarially for
  dependency edges.
- The "no graph database" decision stays honest — it is now backed by a real
  benchmark at scale, not a guess.

### Negative / accepted cost
- `mcp_servers` is a new table. It is justified: no existing structure
  represents an MCP server's identity + trust state, and it references
  `tools`, it does not duplicate it.
- `tools` gains one nullable column. Accepted — it is the minimal link, and
  the alternative (a join table) adds a table and a many-to-many where a tool
  is exposed by exactly one server.
- A dependency edge derived from evidence can go stale (a tool the agent no
  longer calls). `build_for_agent` is idempotent and re-derivable; the read
  API states that absence of an edge is not proof of no dependency.

### Residual risk
- `trust_status` is operator-set (or `DISCOVERED`/`UNKNOWN` on registration).
  A server mis-marked `APPROVED` would not be flagged. The audit trail
  (`GRAPH_MCP_TRUST_CHANGED`, who/prev/new) is the backstop; 5.5 posture and
  5.6 threat detection consume the same data.
- The per-hop tenant bound relies on `DependencyGraphService` /
  `McpServerService` being the only writers of dependency edges. A component
  that inserted edges directly would not get both-endpoints-in-tenant
  validation — the traversal's truncation-at-first-out-of-tenant-node is the
  backstop (`test_ac06_*`).

## Revisit when

- **A measurement shows blast-radius assembly is too slow** — add a
  materialised reachability projection, as its own ADR, with the
  deterministic-and-reconstructable standard ADR-0008 sets (assembly stays
  the fallback and the source of truth).
- **Phase 5.5 raises posture findings over dependencies** — confirm the
  evidence 5.4 surfaces (`evidence.mode`, MCP `trust_status`, provenance) is
  what the finding engine needs, and that 5.4 still only *represents*.
- **Phase 5.6 adds threat detection / tool-poisoning containment** — confirm
  an MCP-exposed tool's schema going through the *existing* validation is
  where poisoning is detected, and that a dependency edge still grants
  nothing to gate on.
- **The runtime gains a real MCP client** (connecting to arbitrary MCP
  servers in prod, currently [DEFERRED]) — wire `McpServerService.record_probe`
  as a genuine fetch-then-write (no DB lock across the probe) and confirm a
  probe failure only marks freshness, never deletes the row.
