# RESULTS_LEDGER — hash-anchored evidence chain (V3 prerequisite)

The V2.1 wrapper limits (`WRAPPER_LIMITS.md` §J) recorded that host-initiated channels — `docker exec`
and the bind mount — sit *outside* the boundary, so a V3 prerequisite was to hash-anchor adversarial
evidence. Built as **lab tooling** ([`lab/harness/ledger.py`](../../../lab/harness/ledger.py)); it
imports nothing from ACT and governs nothing in ACT — it only anchors the lab's own result files.

## Mechanism

An append-only hash chain at `lab/run/results/ledger.jsonl`, one JSON object per line:

```
{seq, ts, path, sha256, prev, entry_hash}
  sha256     = SHA-256 of the file's bytes at anchor time
  prev       = entry_hash of the previous entry ("" for genesis)
  entry_hash = SHA-256 over "seq|ts|path|sha256|prev"
```

`verify` recomputes every `entry_hash`, checks every `prev` pointer, and re-hashes every still-present
file against its anchored `sha256`; any mismatch is **reported, never silently repaired**. Tamper-tested
before use: altering an anchored file one byte makes `verify` exit non-zero and name the file (the
`entry_hash` chain also breaks if a row is edited).

## This run's chain (copy: [`evidence/ledger.jsonl`](evidence/ledger.jsonl))

| seq | file | sha256 (12) | entry_hash (12) |
|---|---|---|---|
| 0 | GENESIS | `9c8e771d0da0` | `8acd8898b7a5` |
| 1 | v3_preflight.json | `97f7a8df43e9` | `965e31d902f0` |
| 2 | v3_injection_results.json | `9c3253c902c1` | `24d9d585578e` |
| 3 | v3_mcp_redteam.json | `34ce887b9fa1` | `206d1086812c` |
| 4 | v3_tool_redteam.json | `1f7f5e85a910` | `da55f7622958` |
| 5 | v3_memory_gap.json | `26a3e101ff20` | `c3dc696c16c1` |
| 6 | v3_canary_integrity.json | `5f56448ad9ee` | `e808e7d9bcf6` |
| 7 | v3_measurements.json | `488a29bc2615` | `0693372898ae` |
| 8 | act_wrapped.log | `e673e5a5ce3a` | `ccba41885c09` |

Final in-lab check at run end: `VERIFY OK: 9 entries, head=ccba41885c095692, chain intact, all present
files match`. Anchored paths are container-relative (`/lab/run/...`); the committed evidence copies carry
identical bytes (the `act_wrapped.log` copy is `evidence/act_wrapped_v3.log`, minus the redaction of a
single synthetic sink token that appears only in the boundary-proof output).

Pre-flight (`lab/harness/v3_preflight.py`) confirmed the ledger active, the canary zero-scan clean, the
positive control firing, and a fresh baseline (0 prior gateway calls) before any batch ran.
