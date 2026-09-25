# RESULTS_LEDGER — hash-anchored evidence chain

Append-only SHA-256 chain (`lab/harness/ledger.py`, the V3 ledger: `entry_hash = SHA256(seq|ts|path|sha256|prev)`).
Every fixture manifest was anchored **before** its measurement ran, every result **after**; the head after the
last anchor is `944303181643bc51…` (25 entries). Full file: [`evidence/ledger.jsonl`](evidence/ledger.jsonl).

`ledger verify` reports **one altered entry, by design of the run**: seq 15 anchored the first `v9_recovery.json`
(recovery executed against the worst/10k database because the worst/100k fixture load had failed on a harness
defect); after the fix, recovery re-ran on the real 100k database and overwrote the same path (seq 19). The
original bytes were copied to `v9_recovery_on_worst10k.json` before the rerun and anchored as seq 22 — its
sha256 equals seq 15's, so nothing was lost or rewritten; the chain itself verifies intact.

| seq | anchored (UTC) | artifact | sha256 | entry hash |
|---|---|---|---|---|
| 0 | 2026-09-25T22:09:43 | `GENESIS` | `9c8e771d0da02bf2…` | `1f381a479ee8165f…` |
| 1 | 2026-09-25T22:09:49 | `lab/run/results/v9_fixture_realistic_100.json` | `614155cfed4f604a…` | `94a9cdc2debf2107…` |
| 2 | 2026-09-25T22:10:14 | `lab/run/results/v9_measure_realistic_100.json` | `1bd8be3f551922d1…` | `58366cfd1f61732a…` |
| 3 | 2026-09-25T22:10:21 | `lab/run/results/v9_fixture_realistic_1000.json` | `bd3337304903b740…` | `7fd4a20800c0923c…` |
| 4 | 2026-09-25T22:11:22 | `lab/run/results/v9_measure_realistic_1000.json` | `95c8c819c8d29dc4…` | `eaa0aaa9de270bbe…` |
| 5 | 2026-09-25T22:11:33 | `lab/run/results/v9_fixture_realistic_10000.json` | `97ff389b00d99f58…` | `1cec56f7284fdf35…` |
| 6 | 2026-09-25T22:13:04 | `lab/run/results/v9_measure_realistic_10000.json` | `1d0ed8bc512fd853…` | `2b682e4cc8b8d57c…` |
| 7 | 2026-09-25T22:13:54 | `lab/run/results/v9_fixture_realistic_100000.json` | `0f4fdff8104ce944…` | `8f4d735e94bab26b…` |
| 8 | 2026-09-25T22:22:30 | `lab/run/results/v9_measure_realistic_100000.json` | `dae7f66d6f787cbd…` | `dee88e0c936e7375…` |
| 9 | 2026-09-25T22:22:36 | `lab/run/results/v9_fixture_worst_100.json` | `60fe26e496731cf7…` | `14ea7af7679f47c6…` |
| 10 | 2026-09-25T22:23:57 | `lab/run/results/v9_measure_worst_100.json` | `74afec080520dac3…` | `63913931059ac5d0…` |
| 11 | 2026-09-25T22:24:05 | `lab/run/results/v9_fixture_worst_1000.json` | `e9706980713459bb…` | `be3d8bbcaefd157f…` |
| 12 | 2026-09-25T22:26:09 | `lab/run/results/v9_measure_worst_1000.json` | `f70437aaf8d34d7d…` | `7028d776d084c490…` |
| 13 | 2026-09-25T22:26:23 | `lab/run/results/v9_fixture_worst_10000.json` | `e833cbe8e4dcde64…` | `86aa736d46452837…` |
| 14 | 2026-09-25T22:35:56 | `lab/run/results/v9_measure_worst_10000.json` | `68bae5bbf7a80001…` | `f8f316e6e2b7846e…` |
| 15 | 2026-09-25T22:39:49 | `lab/run/results/v9_recovery.json` — superseded when recovery re-ran on the worst/100k database; these exact bytes are preserved as `v9_recovery_on_worst10k.json` (seq 22, same sha256) | `c6f1c77baf6d5d26…` | `911859ebb9c287ae…` |
| 16 | 2026-09-25T22:40:01 | `lab/run/results/v9_o11.json` | `b6dda912c5ed7fe8…` | `81d14d8ad8992b66…` |
| 17 | 2026-09-25T22:42:31 | `lab/run/results/v9_fixture_worst_100000.json` | `8d95e38555fd17b3…` | `0038d642bfe0cdb7…` |
| 18 | 2026-09-25T23:06:20 | `lab/run/results/v9_measure_worst_100000.json` | `79243b8ab805a240…` | `95a2924429115409…` |
| 19 | 2026-09-25T23:09:06 | `lab/run/results/v9_recovery.json` | `4169474464f8e09a…` | `9c6f539b3ec4f691…` |
| 20 | 2026-09-25T23:09:08 | `lab/run/results/v9_o11.json` | `b6dda912c5ed7fe8…` | `897f829641e883fc…` |
| 21 | 2026-09-25T23:12:22 | `lab/run/results/v9_recovery_on_worst10k.json` | `c6f1c77baf6d5d26…` | `440b31e7373b85f5…` |
| 22 | 2026-09-25T23:12:22 | `lab/run/results/v9_reach_variant_worst_100000.json` | `58cf22ca1d558d53…` | `a9d60cd0bfa1b716…` |
| 23 | 2026-09-25T23:12:22 | `lab/run/results/v9_run_summary.json` | `973400b75ec07146…` | `bf7bff595de0fa71…` |
| 24 | 2026-09-25T23:12:22 | `lab/run/v9.log` | `749963123d5d1fff…` | `944303181643bc51…` |
