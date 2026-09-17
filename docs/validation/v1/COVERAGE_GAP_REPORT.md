# COVERAGE_GAP_REPORT — v1.0 (2026-09-18)

What ACT at `2b4f57b` does **not** address, with severity, the evidence that establishes the gap, and
what it would take. Nothing here was implemented in V1 (§9 scope). Severity is relative to ACT's thesis
("govern the AI you didn't build, truthfully") and to the retrieved 2026 landscape.

| gap | severity | what is missing (live code) | evidence (register / repo) | what closing it would take (recorded, not built) |
|---|---|---|---|---|
| **G-1 Prompt-injection detection for ACT-run agents** (T1, T2) | HIGH — LLM01 in every edition; observed in the wild (R-033); "still drives most agentic failures" | No content-level signal; `app/threat/rules.py` evidence-gap note; 4.3 only bounds actions | R-001 R-006 R-033 R-070 R-071 | A reason-code taxonomy for content-based denials from the runtime (M1 executor / 4.3 engine) so a deterministic rule can key off it; then a 5.6 rule. Architectural — needs the normal gate. |
| **G-2 Memory / context poisoning surface** (T11, I-1) | MEDIUM for ACT-run agents today (ACT agents hold no persistent memory); HIGH the moment a memory feature ships | No memory, vector or retrieval component exists | R-008; grep of `app/` for memory/embedding/vector: none | Not a control gap yet — a *design constraint*: any future memory feature must land with provenance and poisoning controls (ASI06) on day one. Record as a standing architecture requirement. |
| **G-3 MCP tool-description integrity and change detection** (T9, T8) | HIGH — tool poisoning, rug pulls and STDIO-config RCE are the dominant 2026 MCP findings | 5.4 stores servers/tools and a declared `trust_status`; no description capture, hash pinning, or diff-on-change; no STDIO-transport flag | R-027 R-028 R-029 R-068 | Extend 5.2/5.4 evidence: capture tool descriptions + server version/hash at discovery; a posture rule `mcp_tool_description_changed_since_approval`; an inventory attribute for transport (STDIO vs HTTP). Additive evidence, no new authority. |
| **G-4 Cross-agent correlation and cascade detection** (T13, T25) | MEDIUM | 5.6 rules evaluate one agent over a window; the HF timeline shows the signal was "thousands of low-signal events across systems" | R-044 R-005 | A tenant-level correlation rule over 5.6 signals plus 5.4 blast-radius (agents reachable from a flagged agent). Detection only; containment stays truthful. |
| **G-5 A2A / inter-agent observability** (T12, I-2) | MEDIUM now; HIGH as SAP-style A2A gateways become mandatory (R-060, R-061) | `AGENT_DELEGATES_TO` declared, no producer; no A2A ingestion or Agent Card verification | R-026 R-060 R-061; `app/models/graph.py:68-82` | A 5.2 discovery adapter that reads A2A Agent Cards (signed) as *evidence* and a producer for `AGENT_DELEGATES_TO` from observed delegations — never from configuration. Requires the I-2 design decision in ADR-0017 to be revisited. |
| **G-6 Cloud / SaaS discovery adapters** (T17, I-4) | HIGH for the milestone thesis — ServiceNow ships 30 connectors (R-063); Microsoft/Google/AWS/SAP/Salesforce all host agents ACT cannot see | One adapter: `HttpAgentRegistryAdapter` | R-045 R-047 R-049 R-061 R-062 R-063 | Adapters for at least Azure AI Foundry, AWS Bedrock Agents, Vertex Agent Engine, Copilot Studio, Agentforce, Joule (the seam already exists in `app/discovery/adapters/base.py`). Cloud resources are out of V1 scope. |
| **G-7 Human–agent surface: approval fatigue, flooding, misleading approval text** (T14, I-7) | MEDIUM — ASI09 is a 2026 top-ten entry; approval is ACT's main human control | Approval funnel exists; no per-approver rate limit, no dedup of identical requests, no integrity check on the text an approver sees vs. the action executed | R-005 R-040 R-042; grep of `app/` for approval rate/flood/dedup: none | A rate/dedup policy on approval creation; bind the approval record to a hash of the exact action payload so the executed action cannot differ from what was approved. |
| **G-8 Connector-level failure attribution** (T21, I-3) | LOW–MEDIUM | Runtime-never-knows boundary keeps execution ignorant of connector internals; no attribution field | R-072; `app/integration` | Deliberate; revisit only if incident forensics in V7/V8 shows it blocks root cause. |
| **G-9 Session-temporal policy conditions** | MEDIUM (competitive, not a hole) | 4.3 policies decide per action; AWS AgentCore adds "approval must precede transfer" / "at most N times" / running-budget conditions in one policy (R-047) | R-047 | 4.3 policy predicates over the execution's own prior decisions; M4.4 already tracks spend. |
| **G-10 Agent BOM / OCSF export** | LOW | 5.9 exports signed DSSE bundles; no CycloneDX/SPDX AgBOM, no OCSF events (ACS v0.1) | R-069 | Export-format work in 5.9; alignment item for intake. |

## Gaps confirmed from the master plan (§5 list)

| id | claim | live-code result |
|---|---|---|
| I-1 | no memory-poisoning control surface | **confirmed** — none exists (G-2) |
| I-2 | `AGENT_DELEGATES_TO` vocabulary with no producer | **confirmed** — `app/models/graph.py:68-82`; `test_ac04_graph_never_writes_delegations_and_has_no_agent_delegation_producer` proves it (G-5) |
| I-3 | connector failure attribution deferred | **confirmed** (G-8) |
| I-4 | only the HTTP reference adapter | **confirmed** — `app/discovery/adapters/` holds `http_agent_registry.py` only (G-6) |
| I-7 | no human–agent surface coverage | **confirmed** — approval funnel exists, no fatigue/flooding/text-integrity control (G-7) |

## Newly discovered gaps (not in the master plan's list)

- **G-1** prompt-injection *detection* is explicitly absent by ACT's own evidence-gap note (divergence D-1 in the matrix).
- **G-3** MCP tool-description integrity (divergence D-2).
- **G-4** cross-agent correlation.
- **G-9** session-temporal policy conditions (competitive).
