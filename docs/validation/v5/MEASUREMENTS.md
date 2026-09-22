# MEASUREMENTS — V5: **integrity** (did the picture stay true?) vs **robustness** (did it stay bounded?)

Raw: [`evidence/v5_measurements.json`](evidence/v5_measurements.json). All reconciliation and
blast-radius figures are scored against the hash-anchored
[ground-truth manifest](GROUND_TRUTH_MANIFEST.md), not against "did it return something".

## Integrity — did ACT's picture of reality stay true?

| metric | required | observed |
|---|---|---|
| **false-merge rate** (distinct agents fused and hidden) | 0 | **0 / 1** |
| **false-split rate** (one agent hidden as two) | 0 | **0 / 1** |
| **false-asset promotion rate** (a fabricated asset becoming trusted inventory) | 0 | **0** |
| **weak-signal auto-link rate** (a forged signal clearing the threshold) | 0 | **0** |
| canonical rows after 3 replayed sweeps | 3 (ground truth) | **3** |
| canonical rows after 3 concurrent sweeps | 3 | **3** |
| duplicate external references | 0 | **0** |
| real agents deleted by a forced disappearance | 0 | **0** (2 `STALE_AGENT` findings instead) |
| authority fields injectable via payload | 0 | **0** |
| **blast-radius under-estimation** (a real dangerous path reported safe) | 0 | **0** |
| blast-radius accuracy vs ground truth | exact | **1/1 true paths, 0 over-estimated** |
| **per-hop tenant bound holds** | 100 % | **100 %** |
| poisoned edge granting authority | 0 | **0** (gateway still `403`) |
| **canary escapes** | 0 | **0** |

## Robustness — did the graph stay bounded under attack?

| metric | observed |
|---|---|
| traversal bounded under attack | **yes** |
| depth ceiling enforced | **yes** — `max_depth=9999` → `422 GRAPH_TRAVERSAL_DEPTH_EXCEEDED` |
| cycle-shaped edge | **rejected at creation** (`422`, typed edge schema); traversal completed in **11.9 ms** |
| high-degree node (60-edge hub) | `200` in **13.8 ms** |
| oversized metadata | bounded to 255 / 50 / 255; run completed `201`, no crash |
| malformed item poisoning a batch | **no** — each observation persists in its own SAVEPOINT |
| runs returning 5xx under a concurrent race | **0** — the losing sweep reported a truthful `FAILED` run |

## Pass counts

| batch | pass / total |
|---|---|
| T19a discovery poisoning | **7 / 7** |
| T19b reconciliation | **5 / 5** |
| T20 control graph | **9 / 9** |
| **total** | **21 / 21** |

**Blockers: none.** All seven mandatory-blocker flags false — silent over-merge, silent under-merge,
cross-tenant traversal, false asset trusted, forged-confidence auto-link, poisoned edge granting
authority, blast-radius false-safe.

## Baseline comparison

| | V3 | V4 | V5 |
|---|---|---|---|
| canary escapes | 0 | 0 | **0** |
| per-hop tenant bound | held | held (100 %) | **held (100 %)** |
| false positives / over-blocking | 0 | 0 | **0** |
| the phase's split | contained **but not detected** | held **but not observable** | **picture stayed true, and stayed bounded** |

V5 is the first phase where both axes came out clean together: unlike V3's detection gap and V4's
observability gap, there is no "but" — the inventory and graph resisted poisoning *and* stayed bounded.
Latency is unchanged from baseline; graph queries under attack stayed in the low tens of milliseconds.
