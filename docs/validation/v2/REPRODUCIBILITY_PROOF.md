# REPRODUCIBILITY_PROOF — teardown → rebuild from committed artifacts (V2, 2026-09-19)

Record: `evidence/rebuild_chain.log` (the full chain), `evidence/build_log.json` (per-step timings of
the rebuild), `evidence/lab_up_first.log` (the first build).

## Sequence executed

| step | command | result | time |
|---|---|---|---|
| 0 | first build: `python lab/harness/lab_up.py` | LAB UP (Docker image pulled) | **68.13 s** (docker compose up 56.0 s incl. `postgres:17-alpine` pull; alembic 4.8 s; key bootstrap 2.8 s; process start + readiness 4.5 s) |
| 1 | `python lab/harness/lab_down.py` | killed 9 recorded PIDs + stray listeners; `docker compose down -v --remove-orphans`; removed `lab/.keys`, `lab/run` | ~4 s |
| 2 | post-teardown check | lab listeners: **0**; `act_lab_postgres` containers: **0**; `lab/run`: absent; `lab/.keys`: absent | — |
| 3 | rebuild: `python lab/harness/lab_up.py` | LAB UP with a **new** canary build id (`07a88edd`) and **new** lab key fingerprints (encryption `da67d5db…`, signing `6cc226ac…` vs first build `9e8de197…` / `fbab17c0…`) | **18.38 s** (compose 7.0 s cached image; alembic 4.5 s; bootstrap 2.4 s; readiness 4.4 s) |
| 4 | `python lab/harness/v2_baseline.py` | all ten observations reproduced, **0 findings** | ~22 s wall |
| 5 | `python lab/harness/collector_down_check.py` | collector killed by port, governed call still 200/ALLOWED/DISPATCHED, 0 ACT tracebacks, collector restarted | ~16 s |

Total teardown-to-verified-rebuild: **~60 s** on this host with cached images.

## What "from scratch" meant here

- No lab state survived: the Postgres container and its data were removed, key material deleted,
  run directory deleted. The rebuilt `act_lab` started empty: `alembic upgrade head` created 152 tables
  again; `keys bootstrap` minted a *different* lab identity (fingerprints above), proving the lab does
  not depend on any prior key or data.
- No manual step: the chain ran unattended from `lab_down.py` through `collector_down_check.py`
  (`rebuild_chain.log`).
- Nothing outside `lab/` was needed except the pre-existing host prerequisites (Docker, ACT's venv,
  Node) listed in `LAB_BUILD.md`.

## OS / runtime assumptions

Windows 11 host; Docker 29.6.1; Python 3.13.14 in `backend/.venv`; Node v24.18.0; PostgreSQL 17
(`postgres:17-alpine` image). Loopback ports listed in `LAB_ARCHITECTURE.md`.

## Manual interventions during V2 (each recorded as a documentation gap, now handled)

| gap | what happened | handling |
|---|---|---|
| DG-1 | host-level network isolation is not enforced by the lab (loopback binding + egress allowlists only) | recorded; V3 prerequisite is a VM/network-namespace wrapper |
| DG-2 | POSIX code paths in the harness untested | recorded |
| DG-3 | on Windows the venv launcher's PID is not the listener's; a PID-only kill left the OTLP collector alive during the first down-collector attempt | `lab_down.py` and `collector_down_check.py` kill by port; the rebuild chain verified 0 listeners after teardown |
| DG-4 | `.invalid` e-mail domains are rejected by ACT's validator | harness uses `@example.com` synthetic accounts |
| DG-5 | `TELEMETRY_EXPORT_*` was off in the first lab env, making the down-collector mode vacuous | lab env now exports to the lab collector; V2 still produced no spans (no native executions), recorded in BASELINE_OBSERVATIONS §9 |
| DG-6 | first harness version raised a canary "finding" on the grant-label token, and flagged the Node agent as ACT-dependent by string-matching its own comment | both are harness self-matches; corrected in `v2_baseline.py`; evidence files from the rebuilt run are the record |

None of these required an ACT change. `git diff 2b4f57b -- backend/ frontend/` is empty.
