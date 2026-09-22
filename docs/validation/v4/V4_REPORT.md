# ACT VALIDATION GATE — V4 REPORT (2026-09-22)

Branch `validation/v4-identity` off `ecbcffa`. Attacked ACT's **own identity and authority model**:
identity forgery/replay/escalation (T6), delegation laundering/amplification/truncation (T8), and the
multi-agent / A2A gap with real Wave-2 frameworks at Tier 3–6 (T17 / I-2). **T12 excluded**; no
framework RCE fired. Companion docs: `IDENTITY_REDTEAM_RESULTS.md`, `DELEGATION_REDTEAM_RESULTS.md`,
`WAVE2_AGENT_MATRIX.md`, `MULTIAGENT_A2A_MEASUREMENT.md`, `RESULTS_LEDGER.md`, `MEASUREMENTS.md`,
`REGISTER_UPDATED.csv`; raw evidence under `evidence/`.

## A. Executive verdict

**ACT's identity and authority model held under direct attack, and neither bright line was crossed.**
No external identity became an internal principal, and no path bypassed the gateway (P0 clear). The
authority chain proved un-forgeable, un-amplifiable, un-launderable and never silently truncated (P1
clear). Across 42 adversarial scenarios: identity rejections 10/10 with six distinct rule-specific
error codes, delegation integrity 8/9, per-hop tenant bounding 100%, framework-caused forbidden actions
contained 6/6, false positives 0, canary escapes 0. Real LangGraph and CrewAI multi-agent systems
climbed to Tier 6 performing **14 genuine agent-to-agent handoffs**, of which ACT could observe **zero**
— and, critically, **inferred zero**, leaving its graph honestly empty rather than claiming a
relationship it had no evidence for. The verdict is **CONDITIONAL**: the security invariants passed and
the two findings are a low-severity graph-hygiene gap plus a recorded attribution-scope boundary, both
deferred to the roadmap rather than blocking.

## B. Starting branch + pre-flight

- Branch off `ecbcffa`; `main` untouched at `9667707`; no Docker residue at start.
- **Boundary re-proof** run with ACT running (13 denials / 9 lab-allowed) and with ACT **stopped**
  (14 denials / 8 — ACT itself now unreachable), proving the boundary holds independently of ACT.
  Network `internal=true`, no published ports.
- **Ledger active**, **canary zero-scan clean**, **positive control fires**:
  `PRE-FLIGHT PASS: ledger=True zero_scan_clean=True positive_control=True boundary_present=True`.
- **Framework hygiene:** LangGraph **1.2.12**, CrewAI **1.15.22** (resolved via `importlib.metadata`),
  current releases, installed on a clean python base isolated from ACT's requirements. **No
  code-interpreter tool, no shell tool, no model provider** is configured anywhere, so the VU#221883 RCE
  class is not exercised; CrewAI runs on a deterministic offline stub LLM; telemetry disabled.

## C. Identity results — and the P0 statement

17/17 pass, identity-rejection rate **10/10**. Replay `409 EXTERNAL_REPLAY_DETECTED`; stale timestamp
`401 EXTERNAL_SIGNATURE_EXPIRED`; forged, scheme-confused, body-tampered, path-tampered and
unknown-key all `401 EXTERNAL_SIGNATURE_INVALID`/`_MISSING`; expired `403 EXTERNAL_GRANT_EXPIRED`;
revoked `403 EXTERNAL_GRANT_REVOKED`. Identity substitution denied **and attributed to the signing
agent, not the impersonated one**. Machine-identity collision left two distinct rows with no authority
transfer. Weak-signal reconciliation produced 0 created / 3 linked and no duplicate references.

> **No external → internal identity escalation occurred, and no gateway bypass occurred.** A valid
> signed identity presented at five internal endpoints authenticated at none of them; three bypass
> shapes (unsigned, grant-secret-as-bearer, key-id-without-signature) were all rejected `401`.

## D. Delegation results — laundering, amplification, truncation

13/14 pass, integrity **8/9**, all four P1 flags false. Forged edge `422`; scope outside own org
`403 DELEGATION_EXCEEDS_AUTHORITY`; cross-tenant delegatee edge `404 GRAPH_CROSS_TENANT_ENDPOINT`;
revoked delegation `422`; depth ceiling `422`; cross-tenant chain `404` with no existence leak; an
A→B→A cycle traversed and terminated in 7.6 ms.

**Chain reconstruction completeness.** The control chain returned 3 hops `complete=true`. I then built a
chain that genuinely carries a delegation prefix (delegate A→B, mirror the edge, let B trigger the
execution) and forced `max_depth=1`: it returned the **same 4 hops, still `complete=true`**. I could not
induce a chain that was short while claiming completeness. The code path that would report a missing hop
sets `complete=false` **and** appends a note naming the reason, so incompleteness is reported rather than
hidden. Recorded honestly: no silent truncation observed; the scenario could not be induced by depth
limiting.

## E. Wave-2 frameworks

Both frameworks genuinely executed at every tier. The capability ladder was climbed **in order with each
tier gated on the previous tier's boundary result** — Tier 3 and 4 allowed-only, Tier 5 adding a
forbidden target (`403`), Tier 6 adding an exfil-shaped attempt (`403`). All four gates passed;
**max tier reached 6**. Both agents are AST-asserted to import nothing from `app`.

## F. Multi-agent / A2A measurement — the I-2 map

| question | answer |
|---|---|
| Q1 what can ACT see? | **agents YES, A2A edges NOT_OBSERVABLE** (14 handoffs → 0 edges) |
| Q2 does ACT infer an edge without evidence? | **NO — zero**, and **0 `AGENT_DELEGATES_TO` rows exist anywhere in the database** |
| Q3 per-hop tenant bounding? | **YES**, holds |
| Q4 framework-caused forbidden action contained? | **YES — 6/6** by grant scope |
| Q5 attribution? | **PARTIAL** — acting agent + grant attributed; causing peer NOT_OBSERVABLE |

> **ACT inferred no A2A edge without evidence.** `AGENT_DELEGATES_TO` is declared in the schema with no
> producer and no creation route; across 14 real handoffs in two frameworks ACT left the graph honestly
> empty rather than synthesising a relationship. An inferred edge would have been a false authority
> claim; none occurred.

## G. Canary integrity

**Zero escapes.** Unexpected canary tokens in ACT's own records: `{}`. ACT container log 549 lines with
**0** canary markers and **0** tracebacks. Positive control fires (the operator-supplied grant label,
which ACT is required to store). Evidence copies carry no token values and no key material.

## H. Measurements — integrity vs observability separated

Integrity: identity rejection 10/10 · delegation integrity 8/9 · tenant bound 100% · boundary
containment 6/6 · escalation 0 · bypass 0 · false positives 0 · canary escapes 0 · cycle terminated
7.6 ms. Observability: A2A-edge observability **0/14** · inferred edges **0** · attribution partial ·
authority-chain coverage of external agents **none** (they produce no `agent_executions`). Full table in
`MEASUREMENTS.md`.

## I. Register rows filled

7 rows updated in `REGISTER_UPDATED.csv` (V4 results appended alongside V1–V3, `ACT_test_id` unchanged):
R-004, R-005 (agentic top-10 identity/inter-agent/rogue), R-011, R-012 (NIST agent identity &
authorization — **CONFIRMED**), R-021 (replay/session — **CONFIRMED**), R-026 (A2A spec — **NOT
IMPLEMENTED, measured**), R-046 (agent identity — partial by design). 20 of 72 rows now carry a result
across V1–V4.

## J. Findings

| DEFECT | SEVERITY | PRE-EXISTING / INTRODUCED | ROOT CAUSE | IMPACT | FIX / DEFER | EVIDENCE |
|---|---|---|---|---|---|---|
| **F-1** mirroring the same delegation twice creates **two `DELEGATES_TO` edges** for one delegation row | **Low** | Pre-existing | no uniqueness constraint on (delegation, edge) in the derived graph plane | graph hygiene only — a hop could be double-counted in a traversal/blast-radius view. **No authority widening**: the gateway resolves delegated authority from `delegations` rows via `DelegationService.active_for_user`, and the graph "never … mutates authority" | DEFER | `v4_delegation_results.json` T8-07; DB shows 1 delegation with 2 mirrored edges |
| **F-2** the 5.3 authority-chain surface does **not cover external agents** | **Low** (scope boundary, not a defect) | Pre-existing by design | the chain is keyed on `agent_executions`; gateway-enforced external agents produce none | "who ultimately authorized this" is answered for external actions by the grant + `external_gateway_calls` attribution, not by a reconstructed chain | DEFER — record in the attribution model | `v4_delegation_results.json` T8-13 (0 `agent_executions`, attribution present) |
| **I-2** no producer for agent-to-agent authority edges | Medium | Pre-existing (ADR-0017) | `AGENT_DELEGATES_TO` declared, no producer, no ingestion route | framework-internal A2A authority is invisible; correlation to a causing peer impossible | DEFER → **O-7 / O-4** | `v4_multiagent_results.json` (0/14) |
| carry-over | — | — | — | G-1 (injection not detected), G-3 (MCP integrity/transport), I-1 (memory), OB-1, OB-2 all unchanged from V2/V3 | DEFER | V3 report |

Six **harness** defects (HD-1…HD-6) were found and fixed in lab tooling — including two false FAILs
caused by the harness asserting `401` where ACT documents `403`. These are listed in `RESULTS_LEDGER.md`;
none is an ACT defect, and the corrected assertions matched ACT's documented error mapping rather than
redefining any expectation.

## K. Product-change findings → O-1…O-11

- **O-7** — A2A / agent-card ingestion: give `AGENT_DELEGATES_TO` an evidence-based producer so
  framework-declared relationships can be *ingested* (never inferred).
- **O-4** — cross-agent correlation: correlate a contained boundary action to the peer that caused it.
- Carry-over from V3: **O-1** (injection detection), **O-2/O-7** (memory observability), **O-3** (MCP
  description integrity).
- New minor: uniqueness on mirrored delegation edges (F-1); extend attribution documentation to state
  that external-agent actions are attributed by grant rather than by chain (F-2).

All recorded, none implemented.

## L. P0 / P1 / STOP

**None triggered.** No external→internal escalation, no gateway bypass, no cross-tenant leakage or
traversal, no false containment or authority claim, no machine-identity collision granting another's
authority, no canary escape, no kill-switch bypass, no T12 host-code execution, and no framework RCE
fired. P1: no forgeable, amplifiable, launderable or truncatable chain; ACT inferred no A2A edge.

## M. Artifacts

Lab tooling (all lab-only): `lab/harness/v4_common.py`, `v4_identity.py`, `v4_delegation.py`,
`v4_multiagent.py`; `lab/agents/wave2/langgraph_agent.py`, `crewai_agent.py`;
`lab/wrapper/Dockerfile.wave2`, `v4_run.py`, the `wave2` compose service; encoding fix in the V3/V4
orchestrators. Docs: the eight `docs/validation/v4/` deliverables. Evidence: three batch results,
pre-flight, the hash-chain `ledger.jsonl`, both boundary proofs, the ACT container log, the run log, and
the first-run identity log kept for transparency. No secrets: all values synthetic, the single synthetic
sink token redacted from the committed boundary proofs, no key material.
**`git diff ecbcffa -- backend/ frontend/` is empty.**

## N. Git

Committed on `validation/v4-identity`; `main` untouched at `9667707`; not merged; pushed for review.

## O. V5 readiness

Reusable for V5 (discovery / reconciliation attacks): the wrapper with its per-batch boundary re-proof,
the hash-anchored ledger, the tiered Wave-2 framework harness, and the integrity-vs-observability
reporting split. Already probed lightly and passing: weak-signal reconciliation produced no false merge
(T6-16), which is the seam V5 will attack properly. Still out of scope until their phases: T12 /
framework RCE (needs the VM), runtime-governance and containment attacks (V6), cloud (V8), and any ACT
change. V5 prerequisites carried forward unchanged: re-prove the boundary before each batch, keep
evidence hash-anchored, keep canary escapes at zero and the per-hop tenant bound at 100%.

**VERDICT: V4 CONDITIONAL — REVIEW REQUIRED**
