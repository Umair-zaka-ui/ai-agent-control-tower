# MEASUREMENTS — V7 interoperability

Raw: [`evidence/v7_measurements.json`](evidence/v7_measurements.json).

> **NO SCALE CLAIMS.** V7 measures interoperability: seven real agents doing real work, governed
> truthfully and consistently. It says nothing about throughput, latency at volume, or concurrency
> limits — that is **V9**. No number below licenses a scale claim, and none is offered.

## Interoperability

| metric | value |
|---|---|
| **agents governed truthfully** | **7 / 7** |
| distinct frameworks / stacks | **7 agents across 5 stacks** (stdlib, Node.js, MCP host, LangGraph, CrewAI, OpenAI Agents SDK, Anthropic SDK) |
| **max tier reached** | **T7 for every agent** (T5 skipped — cloud, deferred to V8) |
| independence (imports nothing from `app`) | **7 / 7** |
| reconciliation duplicates vs ground truth | **0** |
| **control-state correctness, per framework** | **7 / 7** — every agent `EXTERNAL`/`REGISTERED`, `GOVERNED` refused `409` |
| **containment effect verified** | **yes** — refusal with no effect, then revocation with a verified `403` |
| blast-radius accuracy vs ground truth | **exact** (1/1 true path, no over- or under-estimation) |
| posture/shadow accuracy | **both directions** — fires unowned, quiet when owned |
| **cross-framework consistency** | **uniform** — 1 distinct allowed status set, 1 distinct forbidden status set |
| **per-hop tenant bound** | **held** |
| **canary escapes** | **0** |

## Detection vs containment (kept separate)

| metric | value |
|---|---|
| denied boundary calls across the whole run | **39** |
| **threat findings raised** | **0** |
| **F6-1 felt** | **YES** — see `FELT_GAP_REPORT.md` |
| containment of those 39 attempts | **39 / 39 denied `403`** |

The contrast is the point: **enforcement was perfect and detection was silent.**

## Multi-agent observability (I-2)

| metric | value |
|---|---|
| **real framework A2A handoffs** | **22** |
| A2A edges observable in ACT | **0** |
| A2A edges **inferred without evidence** | **0** |

## Model and spend accounting

| item | value |
|---|---|
| substrate | local, in-network, OpenAI- **and** Anthropic-compatible; reachable |
| **frontier API used** | **NO** |
| **frontier spend** | **$0.00** (no operator cap and no key provisioned) |
| sensitive data to a paid endpoint | **none — no paid endpoint was contacted at all** |
| honest limitation | the substrate is a **deterministic inference server, not a neural model**: it exercises the frameworks' real tool-calling, handoff and wire paths (what ACT governs), not reasoning quality (what ACT does not) |

## Runtime environments

Two Python interpreters were required (**F7-1**): CrewAI pins `openai<3` and the OpenAI Agents SDK
requires `openai>=3`. Plus Node.js for the custom Node agent. Three runtimes, one governance result.

## Baseline comparison

| | V5 | V6 | V7 |
|---|---|---|---|
| canary escapes | 0 | 0 | **0** |
| per-hop tenant bound | 100 % | 100 % | **held** |
| the phase's headline | picture stayed true and bounded | contains truthfully, says so when it cannot | **governs seven diverse agents uniformly — while its detection plane stays blind to all of them** |
