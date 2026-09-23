# AGENT_MATRIX — seven independent agents, five stacks, tiers T0–T7

Raw: [`evidence/v7_agent_matrix.json`](evidence/v7_agent_matrix.json). Run 2026-09-23 inside the V2.1
egress-deny wrapper. **All 7 agents reached Tier 7. All 7 are independent (import nothing from `app`).**

## The matrix

| agent | framework | version | runtime | max tier | independent | T7 allowed | T7 forbidden | MCP | fs | code | A2A handoffs |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `custom_python` | custom (stdlib) | — | python | **7** | yes | `200 ×5` | `403` | yes | yes | yes | N/A |
| `custom_node` | custom (Node.js built-ins) | — | **node** | **7** | yes | `200 ×5` | `403` | yes | yes | yes | N/A |
| `mcp_client` | custom MCP host | — | python | **7** | yes | `200 ×5` | `403` | yes | yes | yes | N/A |
| `langgraph` | **LangGraph** | 1.2.12 | python | **7** | yes | `200 ×5` | `403 ×2` | yes | yes | yes | 2 |
| `crewai` | **CrewAI** | 1.15.22 | python | **7** | yes | `200 ×4` | `403` | yes | yes | yes | 2 |
| `openai_sdk` | **OpenAI Agents SDK** | 0.22.3 | python (own venv) | **7** | yes | `200 ×4` | `403` | yes | yes | yes | 1 |
| `anthropic_sdk` | **Anthropic SDK** | 1.8.0 | python | **7** | yes | `200 ×5` | `403` | yes | yes | yes | 1 |

Independence is AST-asserted for the Python agents and `require()`-asserted for the Node agent (every
import is a `node:` built-in). Each agent runs in its own OS process with its own ACT grant.

## The tier ladder, and what each tier exercised

| tier | what the agent did | gated on |
|---|---|---|
| T0 | read-only, no tools | — |
| T1 | read-only tool (canary object store) | T0 |
| T2 | controlled write **through ACT's gateway**, plus one forbidden probe | T1 |
| T3 | multi-tool + **MCP** (`initialize` / `tools/list` / `tools/call`) | T2 |
| T4 | filesystem write/read + **sandboxed computation** | T3 |
| **T5** | cloud / SaaS privileges — **SKIPPED** | — |
| T6 | multi-agent delegation (real frameworks; custom agents record N/A) | T4 |
| T7 | bounded high-autonomy multi-step workflow | T6 |

**T5 is skipped and deferred to V8, not fabricated.** There is no cloud adapter yet, so no cloud tier
was simulated. Every agent records the skip explicitly.

**T4 is interoperability only.** The agents write a file inside their own lab work directory and
evaluate an arithmetic expression through an **AST walker** (Python) or a **hand-written parser**
(Node) — never `eval`/`exec`. The point is "does ACT govern an agent that runs code", not escape
testing. **No sandbox-escape or RCE was attempted; that is T12 and needs the VM.**

## Model substrate

All seven agents ran against the lab's **local, in-network model substrate** (`local_model:8814`),
which serves both `/v1/chat/completions` (OpenAI shape, emits `tool_calls`) and `/v1/messages`
(Anthropic shape, emits `tool_use`). The real SDKs pointed their `base_url` at it.

> **Honest limitation, stated plainly:** the substrate is a **deterministic inference server, not a
> neural model**. It exercises the frameworks' real tool-calling loops, handoff machinery and SDK wire
> idioms — which is what ACT observes and governs — but not model reasoning quality, which ACT does not
> govern. No V7 claim depends on reasoning quality.

**Frontier API: NOT USED.** No operator dollar cap and no API key were provisioned, and the local
substrate exercised every framework code path ACT governs, so no claim required a paid run.
**Spend: $0.00. No sensitive data crossed to any paid endpoint — none was contacted at all.**

## Framework hygiene

Versions are pinned and captured at build time. **No code-interpreter tool and no shell tool is
configured anywhere**, so the CrewAI RCE class in the V1 register (R-015 / VU#221883) is not
exercised; telemetry is disabled in both frameworks; the wrapper denies egress regardless.

## F7-1 — two mainstream frameworks cannot share a Python environment

CrewAI 1.15.22 requires `openai<3,>=2.30.0`; the OpenAI Agents SDK 0.22.3 requires `openai<4,>=3.0.0`.
Installing both in one environment fails with `ResolutionImpossible`. The image therefore ships **two
interpreters** — a base environment (LangGraph + CrewAI + Anthropic) and `/opt/sdkvenv`
(openai-agents + Anthropic) — and the harness launches the SDK agent with its own interpreter.

This is an **ecosystem** finding, not an ACT defect, and it is arguably the most operationally
significant thing V7 learned about running diverse agents side by side: an enterprise cannot assume one
Python environment hosts every agent framework. It also happens to match V7's premise that each agent
is independent with its own runtime.
