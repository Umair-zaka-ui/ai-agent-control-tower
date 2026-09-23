# RESULTS_LEDGER — hash-anchored evidence chain (V6)

Same mechanism as V3–V5 ([`lab/harness/ledger.py`](../../../lab/harness/ledger.py)): an append-only
SHA-256 chain over every result file, so a host-initiated channel (`docker exec`, the bind mount)
cannot silently alter recorded evidence. Each entry is `{seq, ts, path, sha256, prev, entry_hash}`
with `entry_hash = SHA256("seq|ts|path|sha256|prev")`.

Copy: [`evidence/ledger.jsonl`](evidence/ledger.jsonl).

| seq | file | sha256 (12) | entry_hash (12) |
|---|---|---|---|
| 0 | GENESIS | `9c8e771d0da0` | `e6f596223b0e` |
| 1 | v3_preflight.json | `97f7a8df43e9` | `26b0a8ed3d58` |
| 2 | **v6_ground_truth.json** | `e91f36276a38` | `d048a76ae736` |
| 3 | v6_containment_results.json | `11501399a618` | `f3f6d3e4462e` |
| 4 | v6_killswitch_results.json | `7ec63d2d244b` | `a4b3b2992ad5` |
| 5 | v6_onepath_results.json | `e5ebfeebb86e` | `94f4cdf38683` |
| 6 | v6_detection_results.json | `ed45a5798711` | `85db9214445d` |
| 7 | v6_measurements.json | `4ef2f828638a` | `653913326d3b` |
| 8 | act_wrapped_v6.log | `4195c96ddc42` | `58d1247b767f` |

Final in-lab check: `VERIFY OK: 9 entries, head=58d1247b767f8379, chain intact, all present files
match` — **0 chain breaks, no `FILE ALTERED` notices**. Every batch ran once and was anchored once; no
harness defect required a re-run this phase.

**The containment ground truth is anchored at seq 2, before any containment result.** That ordering is
the point: the record of what each containment *must actually do* is hash-committed ahead of the
results, so an effect expectation cannot be quietly relaxed afterwards to make a claimed containment
look correct. It is the enforcement-layer equivalent of V5 anchoring the inventory manifest first.

## Pre-flight

Run after the boundary re-proof and before any batch:
`PRE-FLIGHT PASS: ledger=True zero_scan_clean=True positive_control=True boundary_present=True`.

## Lab-tooling changes in V6

| change | why |
|---|---|
| `lab/harness/v6_redteam.py` (new) | containment ground truth + the four batches (T20a, T20b, T21, T16), with every containment scored on effect via direct SQL and canary-target probes |
| `lab/wrapper/v6_run.py` (new) | host orchestrator: boundary re-proof, pre-flight, batch, ACT-log capture and anchoring |

No ACT product code, test, schema, migration or CI file was changed in V6;
`git diff 2dbc169 -- backend/ frontend/` is empty. The V5 hostile discovery source remained in the
compose file but was not driven in this phase.
