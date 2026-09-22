# RESULTS_LEDGER — hash-anchored evidence chain (V5)

Same mechanism as V3/V4 ([`lab/harness/ledger.py`](../../../lab/harness/ledger.py)): an append-only
SHA-256 chain over every result file, so a host-initiated channel (`docker exec`, the bind mount)
cannot silently alter recorded evidence. Each entry is `{seq, ts, path, sha256, prev, entry_hash}`
with `entry_hash = SHA256("seq|ts|path|sha256|prev")`.

Copy: [`evidence/ledger.jsonl`](evidence/ledger.jsonl).

| seq | file | sha256 (12) | entry_hash (12) |
|---|---|---|---|
| 0 | GENESIS | `9c8e771d0da0` | `e195da6466a6` |
| 1 | v3_preflight.json | `97f7a8df43e9` | `8cc2376edd0f` |
| 2 | **v5_ground_truth.json** | `0906a248fc91` | `14a67df68fce` |
| 3 | v5_discovery_results.json | `9bbcba20e096` | `32c721f292d1` |
| 4 | v5_reconciliation_results.json | `f62259f9cb42` | `277a3e800947` |
| 5 | v5_graph_results.json | `fd4b5ffd791d` | `41faad338ef0` |
| 6 | v5_measurements.json | `acaee1e2e6d4` | `b9fb88000115` |
| 7 | act_wrapped_v5.log | `15ffef7bcb46` | `8b92fde452fa` |

Final in-lab check: `VERIFY OK: 8 entries, head=8b92fde452fa9160, chain intact, all present files
match` — **0 chain breaks and no `FILE ALTERED` notices**, because every V5 batch ran once and was
anchored once. (V4's chain deliberately retained superseded anchors from re-runs; this one needed none.)

**The ground-truth manifest is anchored at seq 2, before any attack result.** That ordering matters:
the known-correct picture every later result is scored against is itself hash-committed ahead of the
results, so it cannot be quietly adjusted afterwards to make a reconciliation or blast-radius answer
look correct.

## Pre-flight

Run after the boundary re-proof and before any batch:
`PRE-FLIGHT PASS: ledger=True zero_scan_clean=True positive_control=True boundary_present=True`.

## Lab-tooling changes in V5

| change | why |
|---|---|
| `lab/services/hostile_registry.py` (new, port 8813) | a controllable poisoned discovery source with the same wire shape as the honest one, so ACT's real adapter fetches it over a real socket; its `/_control` plane is refused unless `ACTLAB_ALLOW_ADVERSARIAL=V5` |
| `hostile_registry` service in the wrapped compose | runs inside the same egress-deny network, no published ports |
| `lab/harness/v5_redteam.py`, `v5_graph.py`, `lab/wrapper/v5_run.py` (new) | ground truth + the three batches, and the host orchestrator |

No ACT product code, test, schema, migration or CI file was changed in V5;
`git diff f47439f -- backend/ frontend/` is empty. No harness defects required a re-run this phase.
