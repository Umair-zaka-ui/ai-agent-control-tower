# MCP via the Tool domain (Phase 5.4 / M5.4)

**An MCP server is represented via the existing `Tool` domain, not a second
tool registry.** Full reasoning:
[ADR-0018](../architecture/adr/0018-mcp-representation-via-tool-domain.md).

## The shape

```
mcp_servers                          tools
-----------                          -----
id                                   id
organization_id                      organization_id
name (unique per org)                name
provenance   EXPLICIT|DERIVED|        ...
             DISCOVERED               input_schema   ← the existing M1 contract
trust_status APPROVED|PENDING|        output_schema  ← the existing M1 contract
             REJECTED|UNKNOWN         http_config    ← the existing M1 egress declaration
version                          ┌──  mcp_server_id  (NEW, nullable FK → mcp_servers.id)
endpoint_reference               │
declared_capabilities            │   NULL      → a native tool
owner_id / owner_type            │   set       → a tool exposed by an MCP server
last_probed_at / probe_status ───┘
```

- **One additive column** on `tools` (`mcp_server_id`). AC-15's "additive
  MCP-via-Tool link, justified".
- **`mcp_servers` holds no tools.** It is a provider-of-tools record with a
  trust state. The tools it exposes are ordinary `tools` rows.
- **The relationships are edges**, not columns:
  `AGENT --DEPENDS_ON_MCP_SERVER--> MCP_SERVER --MCP_EXPOSES_TOOL--> TOOL`.

## Why not a second registry

A second MCP tool table would fork the tool domain in three places that must
never diverge:

| Concern | The one path | What a second registry breaks |
| --- | --- | --- |
| Schema validation | M1 validates every tool call's args against `tools.input_schema` before a side effect runs | A poisoned MCP tool schema would bypass the check that exists to catch it |
| Tool gateway | M1 routes every call through one gateway (egress/SSRF, concurrency, retry, audit) | An un-governed MCP invocation path |
| Governance | capability grants, `agent_tools`, risk levels, approval gates key on `tools.id` | MCP tools governed differently from native tools |

## What 5.4 code touches

- `app/models/graph.py` — `McpServer` model, `MCP_SERVER`/`CONNECTOR` node
  types, the dependency `edge_type` vocabulary.
- `app/models/runtime.py` — the one `Tool.mcp_server_id` column.
- `app/graph/mcp.py` — `McpServerService`: register, list, `set_trust`,
  `link_tool` (sets `mcp_server_id` + records `MCP_EXPOSES_TOOL`),
  `record_probe` (fetch-then-write, no lock).
- `migrations/versions/0057_dependency_graph.py` — `mcp_servers`, the column,
  the widened `control_graph_edges` CHECK constraints.

`app/graph/` imports **no** tool-execution, schema-validation or egress code
(`test_ac10_mcp_tool_io_uses_the_existing_schema_validation_and_egress`
asserts this structurally). It represents; it does not enforce.

## Trust / approval

`trust_status` starts at `PENDING` (registered, un-reviewed) or `UNKNOWN`
(provenance could not be established). `POST /graph/mcp-servers/{id}/trust`
moves it (audited: `GRAPH_MCP_TRUST_CHANGED`, previous → new, note). Anything
other than `APPROVED` is an **unapproved dependency** — surfaced as evidence
(`GET /graph/blast-radius/unapproved-mcp`), never silently benign. Unknown ≠
safe. The finding is 5.5's job.
