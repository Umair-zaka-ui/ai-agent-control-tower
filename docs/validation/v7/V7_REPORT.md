# ACT VALIDATION GATE — V7 REPORT (2026-09-23)

Branch `validation/v7-interop` off `e810113`. **Independent powerful-agent interoperability across the
full tier ladder T0–T7**, excluding T12. Seven independent agents on five stacks, doing real
end-to-end work, governed by ACT. Companion docs: `AGENT_MATRIX.md`, `GROUND_TRUTH_MANIFESTS.md`,
`INTEROP_RESULTS.md`, `CONSISTENCY_ANALYSIS.md`, `FELT_GAP_REPORT.md`, `RESULTS_LEDGER.md`,
`MEASUREMENTS.md`, `REGISTER_UPDATED.csv`; raw evidence under `evidence/`.

## A. Executive verdict

**ACT governed all seven independent agents truthfully and identically, and its detection plane saw
none of them.** Every agent — LangGraph, CrewAI, the OpenAI Agents SDK, the Anthropic SDK, a Node.js
agent, a stdlib agent and an MCP host — reached **Tier 7**, landed `EXTERNAL`/`REGISTERED`, had
`GOVERNED` refused `409`, dispatched its allowed capability `200` and had its forbidden capability
denied `403`. Governance was **uniform**: one distinct allowed status set and one forbidden status set
across all five stacks. Containment was truthful and **effect-verified**. Blast radius was exact,
tenant isolation held, **zero canary escapes**, **no P0**. Ten of eleven assertions passed.

The one gap is the phase's real product: **F6-1 is materially felt.** Thirty-nine denied boundary
calls produced **zero** threat findings, because every threat rule keys off `agent_executions` that
gateway-enforced agents never produce. Enforcement worked perfectly and told nobody. The verdict is
**CONDITIONAL** on that finding being accepted and prioritised, not on any failure of governance.

**No scale claims are made anywhere in V7** — seven agents prove interoperability; volume is V9.

## B. Starting branch + pre-flight

- Branch off `e810113`; `main` untouched at `9667707`; no Docker residue at start.
- **Boundary re-proof** with ACT running (13 denials / 9 lab-allowed) and **stopped** (14 / 8):
  the boundary holds independently of ACT. Network `internal=true`, no published ports.
- **Ledger active**, **canary zero-scan clean**, **positive control fires**: `PRE-FLIGHT PASS`.
- **Per-agent ground truth hash-anchored before observation** in every run.
- **Model policy:** local in-network substrate serving both OpenAI and Anthropic wire shapes.
  **Frontier API NOT used; spend $0.00; no sensitive data to any paid endpoint — none was contacted.**
  Honest limitation recorded: the substrate is a **deterministic inference server, not a neural
  model**; it exercises the frameworks' real tool-calling, handoff and SDK wire paths (what ACT
  governs) but not reasoning quality (what ACT does not).
- **Framework hygiene:** versions pinned (LangGraph 1.2.12, CrewAI 1.15.22, OpenAI Agents SDK 0.22.3,
  Anthropic SDK 1.8.0); **no code-interpreter and no shell tool configured anywhere**, so the CrewAI
  RCE class was not exercised; telemetry disabled.

## C. Agent matrix

Seven agents, five stacks, **all reaching Tier 7**, all AST/`require`-asserted independent of `app`,
each in its own OS process with its own ACT grant. **T5 (cloud) skipped and deferred to V8, not
fabricated.** **T4 is interoperability-only**: filesystem writes inside the agent's own work directory
and arithmetic through an AST walker or hand-written parser — never `eval`/`exec` — with **no
sandbox-escape attempted**. Full table in `AGENT_MATRIX.md`.

## D. Interoperability results

**7/7 governed truthfully.** Reconciliation produced **0 duplicates**. Control state was correct for
**every framework**: `EXTERNAL`/`REGISTERED` with `GOVERNED` refused `409` for all seven — the V0.2
ruling holding regardless of how impressive the framework on the other end is. Governance of real work
held at every tier with boundary calls, for every agent. Blast radius matched ground truth exactly.
Posture/shadow proved accurate **in both directions**. Tenant B saw none of tenant A's agents.

## E. Truthful containment across frameworks

Effect-scored, per the V6 discipline: the external `SUSPEND_AGENT` was **REFUSED**, and the agent was
**verified still live** (`200`) immediately afterwards — a status-without-effect would have been caught
there. The authority ACT genuinely holds was then applied and the next call returned **`403`**. Both
halves, on a framework agent, in one sequence.

## F. Consistency analysis

**Uniform. No divergence found.** One distinct allowed status set (`{200}`) and one distinct forbidden
status set (`{403}`) across Node.js and CPython, across two incompatible Python environments, and
across four different wire idioms. The structural reason: ACT governs at the signed-request boundary,
which sees the same thing regardless of what produced the request. Framework diversity lives above the
boundary; the authority decision below it is identical.

The one divergence V7 found is **not ACT's**: **F7-1** — CrewAI pins `openai<3` while the OpenAI
Agents SDK requires `openai>=3`, so the two cannot share a Python environment. An ecosystem
constraint, recorded because "can these agents coexist" is exactly what an interoperability phase
should surface.

## G. Felt-gap report

| gap | felt under real work? | materiality |
|---|---|---|
| **F6-1** detection blind to gateway-enforced agents | **YES, acutely** | **Material — highest priority** |
| **I-2** no A2A edge producer | **YES, bounded** | Moderate |
| **F-2** no authority chain for external agents | felt as a quiet absence | Moderate |
| **I-1** memory modelling | **not felt in V7** | Latent |
| **F5-2** cross-identifier correlation | **not felt in V7** | Latent |

**F6-1 is worse under real workload than in isolation.** The agents ACT is most likely to govern in an
enterprise — independent, framework-built, gateway-enforced — are exactly the ones its detection plane
cannot see. A security team would have watched a clean board while seven agents probed a forbidden
capability 39 times. The counterweight: the data exists (`external_gateway_calls` holds every denial,
attributed), the detection plane simply does not consume it. **A wiring gap, not an architectural
one** — which is why it is both fixable and urgent. Saying plainly that I-1 and F5-2 did **not** bite
is part of the deliverable: not every known gap is equally urgent.

## H. Multi-agent / A2A under real handoffs

**22 genuine agent-to-agent handoffs** across four mechanisms. ACT observed **0** A2A edges and
**inferred 0**. It left the graph honestly empty rather than synthesising a relationship it had no
evidence for. Every framework-caused forbidden action was still contained.

## I. Canary integrity

**Zero escapes.** ACT log clean: 0 canary markers, 0 tracebacks. Committed evidence carries no token
values and no key material.

## J. Measurements

7/7 agents governed, T7 for all, 0 reconciliation duplicates, control state correct per framework,
containment effect verified, blast radius exact, uniform consistency, tenant bound held, 0 canary
escapes, 39 denials → 0 findings, 22 handoffs → 0 edges observed / 0 inferred, $0.00 spend.
**Explicitly: no throughput, latency-at-volume or concurrency claims — that is V9.**

## K. Register rows filled

7 rows updated (V7 appended alongside V1–V6, `ACT_test_id` unchanged): R-004, R-005 (agentic
top-10 — interop confirmed, detection gaps named), R-011, R-012 (agent identity/authorization —
**confirmed across frameworks**), R-015 (CrewAI RCE class **not exercised**, plus F7-1), R-026 (A2A —
**re-measured under real handoffs**), R-045 (felt-gap evidence). 24 of 72 rows now carry a result.

## L. Findings

| DEFECT | SEVERITY | PRE-EXISTING / INTRODUCED | ROOT CAUSE | IMPACT | FIX / DEFER | EVIDENCE |
|---|---|---|---|---|---|---|
| **F6-1 (felt)** detection plane does not cover gateway-enforced agents | **Medium → prioritise** | Pre-existing (V6) | all six threat rules key off `agent_executions`; external agents produce none, and their denials live in `external_gateway_calls` | 39 denials, 0 findings — enforcement works and reports nothing to a security team | DEFER → **highest-priority product change** | `v7_interop_results.json` A8 |
| **F7-1** CrewAI and the OpenAI Agents SDK cannot share a Python environment | Low (ecosystem, **not ACT**) | Pre-existing upstream | `openai<3` vs `openai>=3` | a mixed agent estate cannot assume one runtime; forced two interpreters | DEFER — record in deployment guidance | build log; `Dockerfile.wave2` |
| **I-2 (felt)** no A2A edge producer | Medium | Pre-existing (ADR-0017) | `AGENT_DELEGATES_TO` declared, no producer | 22 real handoffs invisible; cannot answer "which peer caused this" | DEFER → **O-7** | `v7_interop_results.json` A9 |
| carry-over | — | — | — | G-1, G-3, I-1, F-2, F5-x, OB-1, OB-2 unchanged | DEFER | V3–V6 reports |

Three **harness** defects (HD7-1…HD7-2 plus the F7-1 build abort) were found and fixed; none is an ACT
defect. HD7-1 is worth noting: it presented as three separate framework failures but was one missing
setup step (only the first agent row was made `GATEWAY_ENFORCED`).

**No ACT product defect was found in V7.**

## M. Product-change findings → O-1…O-11, re-prioritised by felt impact

1. **Extend detection to the gateway plane (F6-1) — now the top item.** Feed `external_gateway_calls`
   denials into the threat context. Bounded fix, large payoff, and it closes the gap between "ACT
   enforced correctly" and "anyone knew".
2. **O-7 — A2A ingestion (I-2).** Ingest framework-declared relationships; never infer.
3. **F-2 — documentation.** State that external actions are attributed by grant, not by chain.
4. **O-1 (injection detection), O-2 (memory), O-3 (MCP integrity), O-4, O-9** — unchanged, and
   explicitly **not** front-loaded: V7 found no evidence that I-1 or F5-2 currently bite.

All recorded, none implemented.

## N. P0 / STOP

**None triggered.** No false containment claim, no external→internal escalation, no cross-tenant
leakage, no silent merge, no inferred A2A edge, no canary escape, no frontier call carrying sensitive
data (no frontier call at all), no T12 execution or escape.

## O. Frontier-exception accounting

**Not used.** No operator-set dollar cap and no API key were provisioned, and the local substrate
exercised every framework code path ACT governs. **Spend: $0.00 against the cap. No sensitive data
crossed to a paid endpoint — none was contacted.** Had a claim required a paid run that would have
meant sending lab-sensitive data, it would have been recorded `NOT_TESTABLE_WITHOUT_EXPOSURE` rather
than run.

## P. Artifacts

Lab tooling (lab-only): `lab/services/local_model.py`, `lab/agents/v7/` (7 agents + `_agentlib.py`),
`lab/wrapper/Dockerfile.wave2` (two environments + Node), the `local_model` compose service,
`lab/harness/v7_interop.py`, `lab/wrapper/v7_run.py`. Docs: the nine `docs/validation/v7/`
deliverables. Evidence: ground truth, agent matrix, interop results, measurements, pre-flight, the
hash-chain `ledger.jsonl`, both boundary proofs, the ACT container log, the first-run log and the run
log. No secrets: all values synthetic, sink token redacted, no key material.
**`git diff e810113 -- backend/ frontend/` is empty.**

## Q. Git

Committed on `validation/v7-interop`; `main` untouched at `9667707`; not merged; pushed for review.

## R. V7.5 (cloud adapter) + V8 readiness — and what V7 should shape

Reusable: the wrapper with per-batch boundary re-proof, the hash-anchored ledger, the ground-truth
discipline, the **uniform tier protocol** (a new agent implements one interface and joins the matrix),
and the local model substrate.

**What V7 learned that should shape the cloud adapter:**

1. **Wire the gateway plane into detection before the estate grows (F6-1).** Cloud agents will be
   gateway-enforced too. Shipping a cloud adapter on top of a detection plane that cannot see
   gateway-enforced agents would multiply the blind spot rather than add a feature.
2. **Expect heterogeneous runtimes (F7-1).** The adapter should not assume one environment, one SDK
   version, or one dependency tree. V7 could not install two mainstream frameworks together.
3. **Keep the identity boundary exactly where it is.** Uniform governance came *from* the signed-request
   boundary being the only thing ACT looks at. The cloud adapter should extend discovery and inventory,
   not introduce a second authority path.
4. **T5 remains genuinely untested.** No cloud tier was simulated. V8 must build it, not inherit a
   claim from V7.

Still out of scope until their phases: T12 / framework RCE (needs the VM), **scale (V9)**, cloud (V8),
and any ACT change.

**VERDICT: V7 CONDITIONAL — REVIEW REQUIRED**
