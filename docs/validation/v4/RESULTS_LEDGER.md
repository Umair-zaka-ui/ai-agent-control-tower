# RESULTS_LEDGER — hash-anchored evidence chain (V4)

Same mechanism as V3 ([`lab/harness/ledger.py`](../../../lab/harness/ledger.py)): an append-only
SHA-256 chain over every result file, so a host-initiated channel (`docker exec`, the bind mount)
cannot silently alter recorded evidence. Each entry is
`{seq, ts, path, sha256, prev, entry_hash}` with `entry_hash = SHA256("seq|ts|path|sha256|prev")`.

Copy: [`evidence/ledger.jsonl`](evidence/ledger.jsonl).

| seq | file | sha256 (12) | entry_hash (12) |
|---|---|---|---|
| 0 | GENESIS | `9c8e771d0da0` | `a76253613946` |
| 1 | v3_preflight.json | `97f7a8df43e9` | `951fad193327` |
| 2 | v4_delegation_results.json *(superseded)* | `16ece428e9df` | `e7db320723a4` |
| 3 | v4_multiagent_results.json *(superseded)* | `d208790ca7ff` | `1dd68309fda3` |
| 4 | act_wrapped.log | `374886ae82cc` | `dddd9512030b` |
| 5 | **v4_identity_results.json** | `c0a458bc039d` | `004a8d21ef6f` |
| 6 | **v4_multiagent_results.json** (final) | `59d973683273` | `dd77853b7c4f` |
| 7 | **v4_delegation_results.json** (final) | `389e04796c1a` | `d30e63eab218` |

## The chain caught the re-runs, which is the point

Three batches were re-run after harness defects were fixed (see below). The final `verify` reports
**0 chain breaks** — the hash chain itself is intact — together with two `FILE ALTERED after anchor`
notices for the delegation and multi-agent results, because those files now match their **later**
anchors (#6, #7) rather than their first ones (#2, #3).

That is the ledger doing exactly the job it was built for. The superseded anchors were **kept, not
rewritten**: the chain is an honest record that those two files were produced twice, and it would have
flagged any silent edit just as loudly. Starting a fresh ledger for the final run would have produced a
tidier table by destroying that evidence, so it was not done.

## Harness defects found and fixed (none of them ACT defects)

| id | defect | effect | fix |
|---|---|---|---|
| **HD-1** | the identity batch asserted `401` for expired/revoked grants | two false FAILs — ACT's documented mapping is `EXTERNAL_GRANT_EXPIRED` / `EXTERNAL_GRANT_REVOKED` → **403**, and both were genuine rejections | assertion corrected to the documented mapping; the stated expectation ("must reject") never changed. First-run log kept at `evidence/v4_identity_firstrun.log` |
| **HD-2** | a second agent grant reused a fixed label | `409 CONFLICT` (grant labels are unique per agent) aborted the identity batch after T6-14 | unique label per issued grant |
| **HD-3** | `add_user` posted to `/api/v1/users` | `404`; three delegation sub-tests could not run | corrected to `/api/v1/identity/users` (takes role + organization_id) |
| **HD-4** | the cyclic-delegation probe needed two agent nodes the T8 tenant lacked | test reported a GAP for want of nodes, not for an ACT reason | the batch now populates the tenant before building the cycle |
| **HD-5** | the truncation probe ran against a chain with no delegation prefix | a depth limit had nothing to bound, so the probe proved nothing | the batch now builds a genuine delegation prefix (delegate A→B, mirror the edge, B triggers the execution) before forcing the limit |
| **HD-6** | the host orchestrator decoded `docker` output as cp1252 | a `UnicodeDecodeError` in a reader thread on Windows; build output partly lost (return codes unaffected) | `encoding="utf-8", errors="replace"` in the `sh()` helper (also applied to the V3 orchestrator) |

Every one of these is lab tooling. **No ACT product code, test, schema, migration or CI file was
changed in V4**; `git diff ecbcffa -- backend/ frontend/` is empty.

## Pre-flight

`PRE-FLIGHT PASS: ledger=True zero_scan_clean=True positive_control=True boundary_present=True`, run
after the boundary re-proof and before any batch.
