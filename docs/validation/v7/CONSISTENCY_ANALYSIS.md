# CONSISTENCY_ANALYSIS — is ACT's governance uniform across frameworks?

Raw: [`evidence/v7_interop_results.json`](evidence/v7_interop_results.json) (assertion 11) and
[`evidence/v7_agent_matrix.json`](evidence/v7_agent_matrix.json).

**Answer: uniform. No divergence was found.** Across seven agents on five stacks, ACT produced the
same governance outcomes for the same behaviour.

## The comparison

For every agent, the set of statuses ACT returned for *allowed* capability calls and for *forbidden*
capability calls, across the whole tier ladder:

| agent | stack | allowed status set | forbidden status set | control state | `GOVERNED` demand |
|---|---|---|---|---|---|
| `custom_python` | stdlib | `{200}` | `{403}` | `EXTERNAL`/`REGISTERED` | refused `409` |
| `custom_node` | **Node.js** | `{200}` | `{403}` | `EXTERNAL`/`REGISTERED` | refused `409` |
| `mcp_client` | custom MCP host | `{200}` | `{403}` | `EXTERNAL`/`REGISTERED` | refused `409` |
| `langgraph` | **LangGraph 1.2.12** | `{200}` | `{403}` | `EXTERNAL`/`REGISTERED` | refused `409` |
| `crewai` | **CrewAI 1.15.22** | `{200}` | `{403}` | `EXTERNAL`/`REGISTERED` | refused `409` |
| `openai_sdk` | **OpenAI Agents SDK 0.22.3** | `{200}` | `{403}` | `EXTERNAL`/`REGISTERED` | refused `409` |
| `anthropic_sdk` | **Anthropic SDK 1.8.0** | `{200}` | `{403}` | `EXTERNAL`/`REGISTERED` | refused `409` |

**Distinct allowed status sets across all agents: 1. Distinct forbidden status sets: 1.** Uniform.

## Why uniformity was not a foregone conclusion

These agents differ in almost every way that could plausibly produce divergent governance:

- **Runtime:** Node.js versus CPython, and two *different Python environments* (F7-1).
- **Wire idiom:** the OpenAI Agents SDK drives an OpenAI `tool_calls` loop; the Anthropic SDK drives
  an Anthropic `tool_use`/`tool_result` loop; LangGraph drives a state graph; CrewAI drives sequential
  task delegation; the custom agents hand-roll HMAC requests.
- **Concurrency and call shape:** different numbers of boundary calls per tier, different orderings,
  different handoff mechanics.

None of that changed ACT's answer. The reason is structural and worth naming: **ACT governs at the
signed-request boundary**, and that boundary sees the same thing regardless of what produced the
request — a key id, a signature, a capability and a target. Framework diversity lives entirely above
the boundary; the authority decision below it is identical.

## The one place frameworks did diverge — and it is not ACT

**F7-1: CrewAI and the OpenAI Agents SDK cannot coexist in one Python environment** (`openai<3`
versus `openai>=3`). This is a genuine, material interoperability constraint for anyone running a
mixed agent estate, and V7 hit it immediately. It forced two interpreters in the lab image.

It is an **ecosystem** finding, not an ACT finding: ACT governed both agents identically once they were
running. But it belongs in this analysis because "can these agents coexist" is exactly the kind of
question an interoperability phase should surface, and the honest answer is "not in one environment".

## Divergence found: none

No framework slipped a boundary, was mis-reconciled, landed in a different control state, or was
governed differently for the same behaviour. Per the V7 brief, a framework governed *inconsistently*
would be a finding even without a P0 — there is no such finding to report.
