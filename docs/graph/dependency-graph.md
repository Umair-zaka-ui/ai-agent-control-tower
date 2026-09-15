# The Dependency Graph (Phase 5.4 / M5.4)

Phase 5.4 extends the [control graph](./control-graph.md) with **dependency
edges** and makes an **MCP server a first-class, security-relevant
dependency** — represented via the existing `Tool` domain
([ADR-0018](../architecture/adr/0018-mcp-representation-via-tool-domain.md)),
never a second tool registry.

Everything here is **more `edge_type` values on the one
`control_graph_edges` table** and **more recursive-CTE queries over it**.
There is still no graph database and no materialised projection — see
[blast-radius.md](./blast-radius.md) for the benchmark that keeps "no
projection" honest.

## New node types

| Node type | Table | Tenant |
| --- | --- | --- |
| `MCP_SERVER` | `mcp_servers` | `organization_id` |
| `CONNECTOR` | `connector_instances` | `organization_id` |

`CREDENTIAL` is widened from `agent_api_keys` alone to a `UNION` across
`agent_api_keys`, `tool_credentials`, `provider_credentials` and
`connector_credentials` — the label is a non-secret hint (key prefix / secret
hint / provider name / auth scheme); no decrypted value is ever read.

An **external system** (SRS §N) is represented as a `RESOURCE` node
(`resource_type = 'external_system'` or whatever kind fits), matching the
existing `(resource_type, resource_id)` discipline — there is no separate
node type for it.

There is **no `MODEL` node and no `agent→model` edge**: a model is a
`{provider, model}` string on `agent_versions.model_configuration`, not a
governed row. The model-provider dependency surfaces as
`DEPENDS_ON_CREDENTIAL` against the `provider_credentials` row, with the model
id in `evidence`. This is the same restraint 5.3 applied to
`AGENT_DELEGATES_TO`.

## Dependency edge vocabulary

| Edge type | Shape | Meaning |
| --- | --- | --- |
| `DEPENDS_ON_TOOL` | `AGENT → TOOL` | an agent uses a tool |
| `DEPENDS_ON_MCP_SERVER` | `AGENT → MCP_SERVER` | an agent depends on an MCP server |
| `DEPENDS_ON_CREDENTIAL` | `AGENT → CREDENTIAL` | an agent depends on a credential (incl. its model provider's) |
| `DEPENDS_ON_CONNECTOR` | `AGENT → CONNECTOR` | an agent depends on a connector instance |
| `DEPENDS_ON_RESOURCE` | `AGENT → RESOURCE` | an agent depends on a resource directly |
| `MCP_EXPOSES_TOOL` | `MCP_SERVER → TOOL` | a `tools` row is exposed by this MCP server |
| `TOOL_USES_CREDENTIAL` | `TOOL → CREDENTIAL` | a tool authenticates with a credential |
| `TOOL_ACCESSES_RESOURCE` | `TOOL → RESOURCE` | a tool reaches a resource / external system |
| `CREDENTIAL_ACCESSES_RESOURCE` | `CREDENTIAL → RESOURCE` | a credential grants access to a system |

Every dependency edge **references two existing rows** and **grants no
authority**. Reading one, or a blast radius over them, confers nothing —
`AuthorizationGateway` stays the sole decider.

## Observed vs declared

Each dependency edge carries `evidence.mode`:

- **`OBSERVED`** — the platform actually recorded the dependency happening.
  Source: `tool_calls` (this agent invoked this tool in an execution).
- **`DECLARED`** — a binding or config says the dependency exists. Sources:
  `agent_tools` (assignment), `tool_credentials` (bound), `tools.mcp_server_id`
  (link), the published version's model provider → `provider_credentials`.

An observed dependency and a declared one are **different evidence** and are
never conflated (SRS §N). `evidence` also carries `source`, a sample row id,
and — for observed tool use — a call count and last-seen timestamp.
`provenance` on the row is `DERIVED` for evidence-derived edges and `EXPLICIT`
for an operator's declared assertion.

## Deriving edges from evidence

`POST /api/v1/graph/agents/{agent_id}/dependencies/rebuild`
(`DependencyGraphService.build_for_agent`) derives an agent's dependency
edges from existing rows:

- `tool_calls` for the agent's executions → `DEPENDS_ON_TOOL` (`OBSERVED`)
- `agent_tools` assignments → `DEPENDS_ON_TOOL` (`DECLARED`)
- each depended tool's `tool_credentials` → `TOOL_USES_CREDENTIAL`
- each depended tool's `mcp_server_id` → `DEPENDS_ON_MCP_SERVER` + `MCP_EXPOSES_TOOL`
- the published version's model provider → `provider_credentials` row → `DEPENDS_ON_CREDENTIAL`

It is **idempotent** (re-running refreshes evidence, adds nothing new if
nothing changed) and **honest about what it doesn't know**: the response says
*"Absence of an edge is not proof of no dependency (unknown ≠ safe)."*

An operator can also assert a dependency explicitly:
`POST /api/v1/graph/dependency-edges` (authorized via `graph.manage`,
audited, `evidence.mode = DECLARED`, `provenance = EXPLICIT`). The
`(source_type, target_type)` must match the edge type's declared shape; both
endpoints must resolve inside the caller's tenant (a cross-tenant endpoint is
404, no existence leak).

## MCP servers, via the Tool domain

`mcp_servers` carries a server's identity, `provenance`
(`EXPLICIT`/`DERIVED`/`DISCOVERED`), `trust_status`
(`APPROVED`/`PENDING`/`REJECTED`/`UNKNOWN`), `version`, `endpoint_reference`,
ownership and freshness (`last_probed_at`/`probe_status`). It holds **no
tools** — the tools an MCP server exposes are ordinary `tools` rows created
through the existing runtime tool API, linked by the one additive column
`tools.mcp_server_id`. `POST /api/v1/graph/mcp-servers/{id}/tools` sets that
column and records the `MCP_EXPOSES_TOOL` edge; it never creates a tool.

MCP tool I/O is contained by the **existing** authorities: M1 tool-schema
validation catches a poisoned schema, the M1 tool gateway + egress/SSRF guard
contain the call. `app/graph/` imports none of that — it represents, it does
not enforce.

`GET /api/v1/graph/mcp-servers/{id}/trust` … `POST …/trust` changes
`trust_status` (authorized via `graph.manage` — reused, no permission
inflation) and is audited (`GRAPH_MCP_TRUST_CHANGED`, who/prev/new). Two
concurrent reviewers serialize on a row lock.

**No DB lock across an MCP probe.** 5.4 does not connect to arbitrary real
MCP servers in prod ([DEFERRED] — a reference/local representation only).
`McpServerService.record_probe` is a fetch-then-write: the caller does the
network probe with no transaction open, then marks freshness. A probe failure
marks `probe_status`; it never deletes the row (SRS §11).

## Trust as evidence, not enforcement

A server whose `trust_status` is not `APPROVED` is an **unapproved
dependency**. `GET /api/v1/graph/blast-radius/unapproved-mcp` lists every
agent that depends on one, with the edge, the server's trust state and
provenance, and a `why`. This is **evidence for a Phase 5.5 posture
finding** — 5.4 surfaces it; 5.5 raises the finding; 5.6 detects and contains
a live compromise. Unknown ≠ safe.

## What this is not

- Not a second tool registry — MCP via `Tool`, one gateway, one validation.
- Not a graph database — `control_graph_edges` + recursive CTEs.
- Not a posture engine (5.5), not threat detection / containment (5.6), not
  the external gateway (5.7), not the command-center UI — which has since
  shipped in 5.8 and *visualizes* this graph without adding traversal logic
  of its own (`docs/command-center/overview.md`).
- Not a change to tool execution / schema validation / egress — M1 owns
  those, reused unchanged.
