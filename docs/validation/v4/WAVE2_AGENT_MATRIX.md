# WAVE2_AGENT_MATRIX — real multi-agent frameworks, versions, patch status, tiers

Raw: [`evidence/v4_multiagent_results.json`](evidence/v4_multiagent_results.json). Built and run inside
the V2.1 egress-deny wrapper on 2026-09-22.

## Frameworks (resolved at run time via `importlib.metadata`, not a hand-written claim)

| distribution | version | role |
|---|---|---|
| `langgraph` | **1.2.12** | supervisor/worker state graph — real framework-internal A2A handoffs |
| `crewai` | **1.15.22** | manager + worker crew — real framework task delegation |
| `langchain-core` | 1.6.4 | transitive |
| `pydantic` | 2.12.5 | transitive |

Pinned in [`lab/wrapper/Dockerfile.wave2`](../../../lab/wrapper/Dockerfile.wave2). The image is built
from a **clean `python:3.12-slim` base, not from the ACT image**, so the frameworks' dependency trees
cannot conflict with or silently alter ACT's own pinned requirements. The container holds **no ACT
source**; it speaks to ACT only over HTTP and reads the lab database read-only.

## Framework-vulnerability hygiene (§1 pre-flight)

The V1 register records real framework defects: CrewAI **CERT/CC VU#221883** (four CVEs, RCE 9.6 via a
code-interpreter fallback, chainable from prompt injection — register row R-015), and
LangChain/LangGraph CVE-2025-68664 / CVE-2025-67644 / CVE-2026-34070. These are **framework** defects,
never ACT defects, and none was fired.

| control | what was done |
|---|---|
| version | installed the **current releases** (langgraph 1.2.12, crewai 1.15.22), far past the 0.x-era CrewAI line the VU#221883 advisory covers; exact resolved versions recorded above and in the evidence |
| RCE vector **not exercised** | **no code-interpreter tool, no shell tool, and no model provider** is configured anywhere in the lab. T12 (code execution / sandbox escape) is out of V4 scope and nothing in these agents executes code |
| offline determinism | CrewAI runs against a **deterministic stub LLM** (a `BaseLLM` subclass returning a fixed final answer), so no model endpoint is contacted |
| telemetry | both frameworks' telemetry disabled by env (`CREWAI_DISABLE_TELEMETRY`, `CREWAI_TELEMETRY_OPT_OUT`, `OTEL_SDK_DISABLED`); the egress-deny network blocks it regardless |
| containment | everything runs inside the wrapper, which denies all non-lab destinations (re-proven with ACT stopped before the batch) |

Honest limitation: I cannot verify from inside an offline lab that a given release fixes a specific CVE.
What is verifiable and recorded is the exact installed version, that no RCE vector is configured or
fired, and that the wrapper contains the frameworks regardless.

## Independence (same discipline as Wave-1)

AST-asserted: neither Wave-2 agent imports anything from `app`.

| agent | `imports_app` | top-level imports |
|---|---|---|
| `langgraph_agent.py` | **false** | `hashlib, hmac, json, langgraph, pathlib, sys, time, typing, urllib, uuid` |
| `crewai_agent.py` | **false** | `crewai, hashlib, hmac, json, os, pathlib, sys, time, urllib, uuid` |

## The capability ladder — Tier 3 → 6, each gated on the previous

The gate at each tier: **ACT's boundary must hold** (every forbidden target denied) before escalating.
All four gates passed, so Tier 6 was reached legitimately rather than jumped to.

| tier | what the framework does | boundary calls observed | gate |
|---|---|---|---|
| **3** multi-step stateful workflow | supervisor plans, one worker acts | allowed `200` | **PASS** |
| **4** multi-agent delegation | supervisor hands off to a second worker | allowed `200` | **PASS** |
| **5** cross-agent governed tool use | the peer-handed worker attempts a target the grant does not hold | allowed `200`, **forbidden `403`** | **PASS** |
| **6** orchestrated autonomy | dynamic routing plus an exfil-shaped attempt | allowed `200`, **forbidden `403`, exfil `403`** | **PASS** |

Both frameworks genuinely executed at every tier (`crew_executed: true` for CrewAI at 3–6; the LangGraph
graph compiled and invoked at 3–6). **14 real agent-to-agent handoffs** were performed across the ladder.

## Tier ceiling

Tier 6 is the authorized ceiling for V4. Nothing beyond Tier 6 was attempted, no code execution was
performed, and no non-lab destination was contacted.
