# ACT VALIDATION GATE — V5 REPORT (2026-09-23)

Branch `validation/v5-discovery-graph` off `f47439f`. Attacked ACT's **picture of reality** — the
inventory and control graph every downstream governance decision reads. Discovery poisoning (T19a),
reconciliation corruption (T19b), control-graph attacks (T20). **T12 excluded.** Companion docs:
`GROUND_TRUTH_MANIFEST.md`, `DISCOVERY_POISONING_RESULTS.md`, `RECONCILIATION_RESULTS.md`,
`GRAPH_ATTACK_RESULTS.md`, `RESULTS_LEDGER.md`, `MEASUREMENTS.md`, `REGISTER_UPDATED.csv`; raw evidence
under `evidence/`.

## A. Executive verdict

**ACT's picture of reality held against a hostile discovery source, and none of the seven mandatory
blockers occurred.** 21 of 21 scenarios passed. A source that fabricates assets, impersonates, floods
oversized metadata, replays, forces disappearances, forges confidence and asserts its own ownership
produced **evidence and findings — never trusted inventory, never a silent merge or split, never a
deletion**. False-merge rate 0, false-split rate 0, false-asset promotion 0, weak-signal auto-link 0,
blast-radius under-estimation 0, per-hop tenant bounding 100 %, canary escapes 0. The graph stayed
bounded under cycle, depth and high-degree attack, and a poisoned path granted no authority. Unlike V3
(contained but not detected) and V4 (held but not observable), V5 came out clean on **both** axes —
integrity and robustness — with no accompanying gap. No ACT product code, test, schema or CI changed.
The verdict is **CONDITIONAL** only because the findings below, though not defects, are trust
boundaries a reviewer should accept explicitly before pilot.

## B. Starting branch + pre-flight

- Branch off `f47439f`; `main` untouched at `9667707`; no Docker residue at start.
- **Boundary re-proof** with ACT running (13 denials / 9 lab-allowed) and with ACT **stopped**
  (14 / 8 — ACT itself now unreachable), proving the boundary holds independently of ACT. Network
  `internal=true`, no published ports, hostile source inside the same egress-deny network.
- **Ledger active**, **canary zero-scan clean**, **positive control fires**: `PRE-FLIGHT PASS`.
- **Ground-truth manifest recorded and hash-anchored at ledger seq 2 — before any attack result** — so
  the known-correct picture cannot be quietly adjusted afterwards to make an answer look right. True
  inventory: 3 agents, all landing `EXTERNAL` / `DISCOVERED` / unowned / `DRAFT`. True graph: exactly
  one agent reaches the payroll resource.

## C. Discovery poisoning — observations stayed evidence

7/7. False assets were created **only** as unowned `EXTERNAL`/`DISCOVERED` rows — **0 promoted to
trusted inventory**. Source impersonation and cross-tenant source driving both `404`. Oversized
metadata bounded exactly to the canonical widths (name 5 000→**255**, provider 500→**50**, identifier
5 000→**255**) with the run completing and nothing crashing. Replay was idempotent (3 created, then
0/3 linked twice). A forced disappearance deleted **nothing** — 3 agents before and after, with two
reversible `STALE_AGENT` findings instead. An ownership-poisoning payload asserting `GOVERNED`,
`NATIVE`, an owner and `APPROVED` trust was **entirely ignored**: the row landed unowned, external,
`DISCOVERED`, `DRAFT`. Confidence proved **not attacker-controllable** — it is an adapter-class
constant, never read from the payload.

## D. Reconciliation integrity — false-merge 0, false-split 0

5/5, scored against ground truth.

- **Silent over-merge: did not occur.** An identifier collision produced one canonical row — exactly
  what ACT's documented identity signal implies — and **both observations were retained** as
  append-only evidence with the second recorded as a LINK. Nothing was hidden, which is the blocker.
- **Silent under-merge: did not occur.** A split identity produced **two visible unowned rows**. ACT
  does exact-identifier matching only, so it cannot correlate one agent across two identifiers; the
  honest outcome is two visible assets, not a collapse that hides one.
- **NATIVE collision flagged**, 0 agents created, the native agent unchanged at `NATIVE`/`GOVERNED`,
  with a finding naming the conflict and stating "No automatic action taken."
- **Weak-signal forgery: not expressible.** Confidence is adapter-class, and even a cleared threshold
  lands unowned — auto-ownership does not exist in this path.
- **Concurrent race:** three sweeps on real separate Postgres sessions produced 3 agents and **0
  duplicates**; the losing sweep surfaced as a **truthful `FAILED` run, not a 500**.

## E. Control graph — tenant bounding 100 %, no false-safe

9/9. **Blast radius matched ground truth exactly** (1/1 true paths, 0 under-estimated, 0
over-estimated). **Cross-tenant traversal did not occur**: the crossing edge was refused `404
GRAPH_CROSS_TENANT_ENDPOINT` and blast radius returned 404 in **both** directions; `organization_id` is
re-applied at every recursive hop, so the bound does not rest on the edge refusal alone. Depth ceiling
enforced (`max_depth=9999` → `422`). A 60-edge hub answered in 13.8 ms. An empty answer carried its
`incomplete` flag, distinguishing "no recorded path" from a truncated walk — **unknown is not reported
as safe**. A graph path granted **no** authority: the gateway still returned `403`.

**Stated accurately:** the tool→tool cycle-closing edge was rejected `422` by ACT's **typed edge
schema** (each dependency edge type permits exactly one source→target node-type pair), so a cycle of
that shape cannot be expressed at all. I did **not** form a real data cycle here and do not claim to;
V4 exercised a real A→B→A cycle that terminated in 7.6 ms.

## F. Canary integrity

**Zero escapes.** Unexpected canary tokens in ACT's own records: `{}`. ACT container log 327 lines,
**0** canary markers, **0** tracebacks. Positive control fires. Committed evidence carries no token
values and no key material.

## G. Measurements — integrity vs robustness separated

Integrity: false-merge 0, false-split 0, false-asset promotion 0, weak-signal auto-link 0,
blast-radius under-estimation 0, tenant bound 100 %, authority fields injectable 0, canary escapes 0.
Robustness: traversal bounded yes, depth ceiling enforced, cycle shape rejected, 60-edge hub 13.8 ms,
oversized metadata bounded, no 5xx under a race, one malformed item cannot poison a batch. Full tables
in `MEASUREMENTS.md`.

## H. Register rows filled

6 rows updated in `REGISTER_UPDATED.csv` (V5 appended alongside V1–V4, `ACT_test_id` unchanged):
R-004 and R-005 (agentic supply chain / rogue agents at the inventory layer), R-009 (supply-chain
rug-pull analogue — **contained** at inventory), R-012 (NIST agent identification — **confirmed** under
a poisoned intake), R-020 (SSRF at the discovery fetch — **contained**), R-035 (cross-tenant blind
spots — **contained**). 22 of 72 rows now carry a result across V1–V5.

## I. Findings

| DEFECT | SEVERITY | PRE-EXISTING / INTRODUCED | ROOT CAUSE | IMPACT | FIX / DEFER | EVIDENCE |
|---|---|---|---|---|---|---|
| **F5-1** a hostile source can cause **rows to exist** (unowned, external, `DISCOVERED`) | Informational — by design | Pre-existing | that is what a discovery source is for; creation is the documented outcome of evidence clearing the threshold | inventory noise from a hostile source; every row is unowned and shadow-flagged, and none is trusted | DEFER — the containment (unowned landing + shadow finding) is the design | `v5_discovery_results.json` V5-D1 |
| **F5-2** ACT cannot correlate one agent across two identifiers | Low — documented non-goal | Pre-existing | exact-identifier matching only; fuzzy matching is a recorded future extension | a renamed/re-identified agent appears as two visible rows; **no hiding**, and the absence of fuzzy matching is what makes a forged merge impossible | DEFER → O-9 (identity correlation), with the trade-off stated | `v5_reconciliation_results.json` V5-R2 |
| **F5-3** blast radius is only as true as its recorded edges; an authorized operator can assert a false dependency | Low — trust boundary | Pre-existing | declared edges are operator assertions | a false edge distorts the picture, but requires an authorized internal principal, resolves both endpoints in-tenant, and is stamped `mode: DECLARED, source: operator, created_by` — attributable, not silent | DEFER — record the trust boundary in the blast-radius documentation | `v5_graph_results.json` V5-G2 |
| carry-over | — | — | — | G-1 (injection not detected), G-3 (MCP integrity/transport), I-1 (memory), I-2 (A2A edges), F-1/F-2 (V4), OB-1, OB-2 all unchanged | DEFER | V3/V4 reports |

**No ACT product defect was found in V5**, and no finding is a blocker.

## J. Product-change findings → O-1…O-11

- **O-9 (identity correlation)** — optional, evidence-based correlation of one agent across changed
  identifiers, with any merge surfaced as a reviewable finding rather than an automatic action
  (F5-2). The current no-fuzzy-matching stance is a security *feature*; any extension must preserve
  "ambiguity becomes a finding".
- Documentation-level: state the blast-radius trust boundary explicitly — a declared edge is an
  attributable operator assertion, not an observed fact (F5-3).
- Carry-over: **O-1** (injection detection), **O-2/O-7** (memory + A2A observability), **O-3** (MCP
  description integrity), **O-4** (cross-agent correlation).

All recorded, none implemented.

## K. Blockers / P0 / STOP

**None triggered.** All seven mandatory-blocker flags false: silent over-merge, silent under-merge,
cross-tenant graph traversal, false asset persisting as trusted inventory, forged-signal
high-confidence auto-link, poisoned edge granting authority, blast-radius false-safe. No canary escape,
no cross-tenant leakage, no T12 host-code execution.

## L. Artifacts

Lab tooling (all lab-only): `lab/services/hostile_registry.py` (the controllable poisoned source, V5-gated),
the `hostile_registry` compose service, `lab/harness/v5_redteam.py`, `lab/harness/v5_graph.py`,
`lab/wrapper/v5_run.py`. Docs: the eight `docs/validation/v5/` deliverables. Evidence: the ground-truth
manifest, three batch results, measurements, pre-flight, the hash-chain `ledger.jsonl`, both boundary
proofs, the ACT container log, the batch log and the run log. No secrets: all values synthetic, the
single synthetic sink token redacted from the committed boundary proofs, no key material.
**`git diff f47439f -- backend/ frontend/` is empty.**

## M. Git

Committed on `validation/v5-discovery-graph`; `main` untouched at `9667707`; not merged; pushed for
review.

## N. V6 readiness

Reusable for V6 (runtime / governance / containment attacks): the wrapper with its per-batch boundary
re-proof, the hash-anchored ledger, the ground-truth-manifest discipline (V6 should score containment
against a known-true runtime state the same way), and the integrity-vs-robustness reporting split.
Already established and relevant: containment was proven **truthfully refused** for external agents in
V2 and revocation proven effective, which is the seam V6 will attack properly. Still out of scope until
their phases: T12 / framework RCE (needs the VM), cloud (V8), and any ACT change. Prerequisites carried
forward unchanged: re-prove the boundary before each batch, hash-anchor evidence, keep canary escapes at
zero and the per-hop tenant bound at 100 %.

**VERDICT: V5 CONDITIONAL — REVIEW REQUIRED**
