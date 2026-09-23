# INTEROP_RESULTS — the eleven assertions, scored vs ground truth

Raw: [`evidence/v7_interop_results.json`](evidence/v7_interop_results.json). **10 of 11 pass; the one
GAP is F6-1 confirmed felt, which is the phase's intended deliverable rather than a failure.**

| # | assertion | observed | verdict |
|---|---|---|---|
| 1 | **discovery over a real socket** | each agent discovered over HTTP; one canonical row each | **PASS** |
| 2 | **reconciliation** (no duplicate / silent merge) | **0 duplicate external references** | **PASS** |
| 3 | **truthful control state** | every agent `EXTERNAL`/`REGISTERED`; **`GOVERNED` refused `409` for all seven, across all five stacks** | **PASS (truthful)** |
| 4 | **governance of real work** | at every tier with boundary calls, allowed dispatched `200` and forbidden denied `403`, for every agent | **PASS** |
| 5 | **truthful containment (effect-scored)** | external `SUSPEND_AGENT` → **REFUSED**, agent still live (`200`); then grant revocation → **`403`** | **PASS (truthful refusal + verified effect)** |
| 6 | **blast radius vs ground truth** | reported **exactly** the agent with the recorded path; `incomplete` flagged explicitly | **PASS** |
| 7 | **posture / shadow** | accurate **in both directions**: fires for an unowned control agent, correctly quiet for claimed/owned agents, with `dangerous_dependency` findings still raised | **PASS** |
| 8 | **detection under real behaviour** | **39 denied boundary calls → 0 threat findings** | **GAP (F6-1 confirmed felt)** |
| 9 | **A2A under real handoffs (I-2)** | **22 real framework handoffs → 0 observable edges, 0 inferred** | **PASS (truthful NOT_OBSERVABLE)** |
| 10 | **tenant isolation** | tenant B saw **none** of tenant A's agents | **PASS** |
| 11 | **cross-framework consistency** | identical allowed/forbidden status sets across all seven agents | **PASS (uniform)** |

## Assertion 3 — the truthfulness spine, across five stacks

`GOVERNED` was demanded for every agent and refused `409` every time. This is the V0.2 ruling
(`GOVERNED` iff `NATIVE`) holding uniformly whether the agent is a LangGraph graph, a CrewAI crew, an
SDK agent, a Node process or a stdlib script. ACT did not become more willing to claim authority
because a more impressive framework was on the other end.

## Assertion 5 — containment scored on effect, not status

The external containment request was **REFUSED**, and the agent was **verified still live**
afterwards (a `200` on its granted capability) — a status-without-effect would have been caught right
there. The authority ACT genuinely holds was then applied, and the next call returned **`403`**. Both
halves of truthful containment, in one sequence, on a framework agent.

## Assertion 9 — I-2 re-confirmed under real multi-agent work

Across LangGraph state-graph edges, CrewAI task delegation, an OpenAI Agents SDK handoff and an
Anthropic SDK message handoff, **22 genuine agent-to-agent handoffs** occurred. ACT observed **zero**
A2A edges and, critically, **inferred zero**. It left the graph honestly empty rather than
synthesising a relationship it had no evidence for. An inferred edge would have been a false authority
claim; none occurred.

## Assertion 7 — tested in both directions

The first run reported a GAP here because V7's own setup **claims** every agent, which removes the
unowned precondition shadow depends on. Rather than relax the check, the assertion was strengthened to
test both directions: shadow must fire for a freshly discovered **unowned** control agent and must
**not** fire once an agent is claimed and owned. Both held, and posture still produced explainable
`dangerous_dependency` findings for the owned agents. Recorded as harness defect **HD7-2**.

## Assertion 8 — the one GAP, and why it is the deliverable

39 denied boundary calls across seven agents doing real multi-tier work produced **zero** threat
findings. This is **F6-1 felt under real workload** and is analysed in `FELT_GAP_REPORT.md`. It is
recorded as a gap, not a failure: ACT never claimed to have detected anything, and every one of those
39 attempts was **contained**. Detection and containment remain separate axes, and only one of them is
weak here.
