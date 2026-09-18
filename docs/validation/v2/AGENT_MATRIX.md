# AGENT_MATRIX — Wave-1 at Tier 0–2 (V2, 2026-09-19)

Per-agent record (master plan §K). "Observed" columns come from the rebuilt lab's baseline run
(`evidence/v2_baseline.json`, build `07a88edd`); the first build (`b54de795`) produced identical
control-state and affordance observations.

| field | #1 Python agent | #2 Node agent | #3 MCP client |
|---|---|---|---|
| creator / framework | lab (V2), plain Python stdlib, no framework | lab (V2), plain Node.js built-ins | lab (V2), plain Python stdlib, MCP-shaped JSON-RPC client |
| model | none (deterministic; no LLM in Tier 0–2) | none | none |
| runtime | `python` 3.13 separate OS process | `node` v24.18 separate OS process | `python` 3.13 separate OS process |
| identity mechanism toward ACT | scoped ACT grant: `X-ACT-Key-Id` + HMAC-SHA256 over method/path/ts/nonce/body-sha256 (ACT-HMAC-SHA256); no ACT user, no session | same protocol, Node `crypto` implementation | same protocol |
| tools | T1: canary object-store listing (read-only); T2: `http_tool.invoke` → canary finance `/purchase` **through ACT's gateway** | same | T1: `initialize`, `tools/list`, `tools/call payroll_read` on the trusted MCP server; T2: `http_tool.invoke` through ACT |
| MCP dependencies | modelled in ACT (`DEPENDS_ON_MCP_SERVER` → lab-payroll-mcp, `DEPENDS_ON_TOOL` → payroll_read, `TOOL_ACCESSES_RESOURCE` → canary payroll) | none modelled | trusted server only (live), not modelled as an edge in V2 |
| memory | none (stateless process) | none | none |
| permissions | its own config file (canary-tagged); the grant's scope: exactly one capability on exactly one target | same | same |
| network | loopback only: 127.0.0.1:8802 (ACT), :8821 (object store) | same | loopback: :8831 (trusted MCP), :8802 |
| filesystem | reads its config JSON | reads its config JSON | reads its config JSON |
| cloud access | none | none | none |
| **ACT discovery method** | 5.2 `HTTP_AGENT_REGISTRY` adapter over a real socket (lab registry :8811); `external_reference = lab://wave1/python-agent/<build>` | same, `lab://wave1/node-agent/<build>` | same, `lab://wave1/mcp-client/<build>` |
| **ACT enforcement capability** | boundary only: authorize/deny `http_tool.invoke` calls it routes through ACT; revoke its grant. Cannot stop the process | same | same |
| **expected truthful control state** | DISCOVERED on discovery → CLAIMED → REGISTERED after claim/registration; GOVERNED **unreachable** (ADR-0023) | same | same |
| **observed state** | DISCOVERED (`origin_category=EXTERNAL`, owner none) → after claim/register: REGISTERED, `external_enforcement_mode=GATEWAY_ENFORCED`; GOVERNED request → 409 `CONTROL_STATE_ORIGIN_INCOMPATIBLE` both before claim and after REGISTERED | identical | identical |
| observed affordances (5.7/5.8) | `reaches_boundary_calls=true`, `reaches_agent_execution=false`, display "ACT authorizes this agent's capability calls that route through ACT's gateway." | identical | identical |
| observed T2 governed call | allowed target: 200 `ALLOWED`/`DISPATCHED` (canary finance received it); forbidden target: 403 `DENIED`/`NOT_DISPATCHED` | identical | allowed: 200 `ALLOWED`/`DISPATCHED` |
| observed containment | `SUSPEND_AGENT` → 201 with `status=REFUSED`, reason "ACT has no enforcement authority over this agent (control_state='REGISTERED', requires 'GOVERNED')…", `authority_ref=null`; grant revoke → 200; next call 403, zero further dispatches | (containment attempted on the Python agent only; the ruling is identical by construction) | — |
| **divergence** | **none** | **none** | **none** |
| tier ceiling in V2 | T2 | T2 | T2 |

## Independence proof

| agent | check | result |
|---|---|---|
| Python agent | AST of `lab/agents/python_agent.py`: imports `hashlib, hmac, json, pathlib, sys, time, urllib.error, urllib.request, uuid` — nothing from `app` | independent |
| MCP client | AST of `lab/agents/mcp_client.py`: same stdlib set | independent |
| Node agent | `require()` list: `node:crypto`, `node:fs`, `node:http` — all Node built-ins | independent. Note: the first harness version also flagged `requires_act=true` because its check string-matched the word "backend" in the file's own comment; the `requires` list in the evidence is the real check, and the harness was corrected (see LAB_BUILD DG list) |

All three run in their own OS process (`subprocess.run` from the harness), with no database handle, no
ACT session, and only the grant credential ACT issued them.
