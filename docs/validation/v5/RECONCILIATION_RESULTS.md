# RECONCILIATION_RESULTS — V5 (T19b): merge/split integrity, scored vs ground truth

Raw: [`evidence/v5_reconciliation_results.json`](evidence/v5_reconciliation_results.json). Fired
2026-09-23. **5 / 5 pass. False-merge rate 0. False-split rate 0. No blocker.**

## The integrity core

`ReconciliationService` derives canonical state from evidence with a **deterministic, explainable**
rule set: the sole identity signal is an exact `(organization_id, external_reference)` match — there is
no fuzzy or name-similarity matching, and that is a documented non-goal, not an omission. Exactly three
outcomes exist: **CREATE**, **LINK**, **FLAG**. NATIVE collision is checked *first* and always flags.
Anything below `LINK_CREATE_CONFIDENCE_THRESHOLD = 0.75` always flags. A LINK updates discovery
metadata **only** — never ownership, control state or lifecycle status.

| # | scenario | attack | observed vs ground truth | verdict |
|---|---|---|---|---|
| V5-R1 | **identifier collision** (over-merge probe) | two genuinely *different* agents advertised under **one** identifier | **1 canonical row** (created 1, linked 1) and **both observations retained** as evidence | **PASS (deterministic, nothing hidden)** |
| V5-R2 | **split identity** (under-merge probe) | **one** real agent advertised under **two** identifiers, to evade correlation | **2 visible rows**, both unowned `DISCOVERED`; neither hidden | **PASS (no hidden split)** |
| V5-R3 | **NATIVE collision** | a hostile observation contrives the identifier of a NATIVE, ACT-governed agent | **flagged**; 0 agents created; the native agent stayed `NATIVE` / `GOVERNED`; the finding names the conflicting agent id and says "No automatic action taken" | **PASS (flagged finding)** |
| V5-R4 | **weak-signal high-confidence forgery** | forge signals to clear the 0.75 threshold and auto-own | not expressible: confidence is an adapter-class constant, and even a cleared threshold lands **unowned** — auto-ownership does not exist | **PASS (not forgeable)** |
| V5-R5 | **concurrent reconciliation race** | 3 concurrent sweeps of one source on real separate Postgres sessions | 3 canonical agents, **0 duplicate references**; one run `SUCCEEDED` creating 3, one `SUCCEEDED` linking 3, one reported **`FAILED`** — truthfully, not as a 500 | **PASS (one canonical effect)** |

## The two mandatory blockers, answered

**Silent over-merge: did not occur.** The collision scenario produced one canonical row for one
identifier — which is exactly what ACT's documented identity signal implies, since a source claiming a
single identifier for two agents is asserting they are one asset. The blocker is *hiding* an agent, and
nothing was hidden: **both observations were retained** as append-only evidence, the second was recorded
as a LINK, and both are auditable. The derivation is inspectable and reconstructable, not opaque.

**Silent under-merge: did not occur.** The split-identity scenario produced **two visible, unowned
rows**. ACT cannot correlate one agent across two identifiers because it does exact-identifier matching
only — a documented limitation, and the honest outcome is two visible assets rather than a silent
collapse that would hide one. Correlating renamed or re-identified agents is a recorded future
extension; the absence of fuzzy matching is precisely what makes a *forged* high-confidence merge
impossible.

## The race, precisely

This exercised the V0-era concurrency path. Of three concurrent sweeps, one was reported `FAILED` in
its run record while the other two succeeded — the losing writer surfaced as a **truthful failed run**
rather than a 500 or a duplicate. The canonical outcome was exactly the ground-truth 3 agents with zero
duplicate external references, which is the create-race fallback to LINK behaving as designed.

## Score against ground truth

| metric | ground truth | observed | result |
|---|---|---|---|
| false-merge rate (distinct agents fused and hidden) | 0 | **0** | PASS |
| false-split rate (one agent hidden as two) | 0 | **0** | PASS |
| canonical rows after replay | 3 | **3** | PASS |
| canonical rows after a race | 3 | **3** | PASS |
| duplicate external references | 0 | **0** | PASS |
| ambiguity resolved to a finding rather than an action | yes | **yes** (NATIVE collision) | PASS |
