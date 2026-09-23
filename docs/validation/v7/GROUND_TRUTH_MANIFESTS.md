# GROUND_TRUTH_MANIFESTS — the expected picture, per agent, before observation

Raw: [`evidence/v7_ground_truth.json`](evidence/v7_ground_truth.json), hash-anchored in the ledger
**before** any governance observation (see `RESULTS_LEDGER.md`).

V5 established that a picture is only meaningful when scored against a known-correct one, and V6
applied it to enforcement effects. V7 applies it to **governance of diverse agents**: "governed
truthfully" means "matches this manifest", not "returned something".

## What is fixed in advance, for every one of the seven agents

| field | expected value |
|---|---|
| `origin_category` | **`EXTERNAL`** — ACT did not build any of these agents |
| `control_state` | **`REGISTERED`** after claim; **`GOVERNED` must be UNREACHABLE** |
| enforcement mode | **`GATEWAY_ENFORCED`** — authorizes boundary calls; does **not** run the agent |
| ACT enforcement capability | bound its reach (grant scope, revocation). **No agent-lifecycle containment**, because it is not `GOVERNED` |
| tools | one granted finance capability (**must dispatch**), one forbidden capability (**must be denied**) |
| MCP dependency | `lab-payroll-mcp` (trusted) from T3 upward |
| memory | **none modelled in ACT** (I-1) |
| expected A2A edges in ACT | **0** — `AGENT_DELEGATES_TO` has no producer (I-2) |
| tier ceiling | 7 |
| T5 | **SKIPPED** — cloud/SaaS needs the V8 adapter; deferred, not fabricated |
| independence | imports nothing from `app` |

## Why this matters for the truthfulness claim

Two of these expectations are the ones an untruthful system would get wrong, and they are fixed here
before anything is observed:

- **`GOVERNED` must be unreachable.** ACT did not build these agents, so claiming it governs them
  would be a false authority claim. The manifest says so in advance for all seven, across five
  different stacks, so a framework-specific slip would be visible.
- **Zero A2A edges expected.** Real framework handoffs happen during the run (22 of them). The
  manifest commits in advance to expecting ACT to observe **none** and to **infer none** — so an
  inferred edge would be scored as the defect it is, rather than mistaken for a feature.

## Scoring rule

> Governance is scored against this manifest; containment is scored on **effect** (the V6 discipline).

The shared governed surface (one MCP server registration, the granted/forbidden tools, and the
dependency path used for blast radius) is recorded alongside the per-agent manifests so the blast
radius answer has a known-true value to be compared against.
