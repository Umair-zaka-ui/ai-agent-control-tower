# LAB_BUILD — committed, runnable (V2)

Everything the lab needs is under `lab/` on `validation/v2-lab`. No ACT product code, test, migration
or CI file was changed; `git diff 2b4f57b -- backend/ frontend/` is empty.

## Prerequisites (host)

| requirement | as verified 2026-09-19 |
|---|---|
| Docker (compose v2) | Docker 29.6.1 |
| ACT's backend venv at `backend/.venv` (Python 3.13.14, `requirements.txt` installed) | present |
| Node ≥ 20 on PATH (for the Node agent) | v24.18.0 |
| Free loopback ports 5433, 8802, 8811, 8812, 8821–8825, 8831–8835 | free (dev API on 8000 and dev Postgres on 5432 untouched) |
| OS | Windows 11 (paths use `.venv\Scripts\python.exe`; `lab_up.py` picks `bin/python` on POSIX but that path has not been exercised — DG-2) |

## Files

| path | role |
|---|---|
| `lab/docker-compose.lab.yml` + `lab/initdb/01_lab_databases.sql` | lab PostgreSQL 17 (`act_lab`, `lab_payroll`), loopback 5433, no volume |
| `lab/env/act-lab.env` | ACT's lab environment — synthetic secrets, dedicated DB, lab key paths, OTLP export to the lab collector, rate limiting off for the harness's burst of tenant registrations (documented deviation), notifications off |
| `lab/canaries.py` | generates `lab/run/canaries.json` (unique tokens, fake PII, fake credentials) per build |
| `lab/services/canary_zone.py` | object store, mailbox, finance tool, metadata decoy, attacker-sim; seeds `lab_payroll` |
| `lab/services/registry.py` | the Wave-1 agent registry ACT discovers |
| `lab/services/otlp_collector.py` | OTLP/HTTP receiver; `--down` mode |
| `lab/mcp/mcp_server.py`, `stdio_mcp_server.py`, `stdio_config.json` | the five MCP-shaped servers + the inert STDIO artifact |
| `lab/agents/python_agent.py`, `node_agent.js`, `mcp_client.py` | Wave-1 agents |
| `lab/adversary/` | provisioned, idle |
| `lab/harness/lab_up.py` / `lab_down.py` | build / destroy |
| `lab/harness/v2_baseline.py` | the §6 observation run → `lab/run/results/v2_baseline.json` |
| `lab/harness/collector_down_check.py` | the down-collector observation |

## Build

```
python lab/harness/lab_up.py            # ~70 s on this host (Docker image cached)
python lab/harness/v2_baseline.py       # ~10 s
python lab/harness/collector_down_check.py
```
(`python` = `backend/.venv/Scripts/python.exe`.) `lab_up.py` writes `lab/run/build_log.json` with every
step's duration and `lab/run/pids.json`.

What `lab_up.py` does, in order: `docker compose up -d --wait` → generate canaries → `alembic upgrade
head` with the lab env (`DATABASE_URL` of `act_lab`) → `python -m app.security.keys bootstrap` with
`ENCRYPTION_KEY_ALLOW_BOOTSTRAP=true` **for that single command** (the running ACT keeps the gate off) →
start canary zone, registry, collector, five MCP servers, then ACT via `uvicorn app.main:app --host
127.0.0.1 --port 8802` with the lab env exported into its process (pydantic-settings: process env beats
`backend/.env`, so the developer's real `.env` values never reach the lab instance) → readiness waits.

## Teardown

```
python lab/harness/lab_down.py
```
Kills recorded PIDs **and any stray listener on a lab port** (the venv launcher's PID is not the
listener's on Windows — found during V2, handled by port), `docker compose down -v --remove-orphans`,
deletes `lab/.keys/` and `lab/run/`. Never touches `backend/.keys/`, `backend/.env` or the dev database.

## Documented deviations from production defaults (lab env only)

- `RATE_LIMIT_ENABLED=false` — the harness registers tenants and issues grants in a burst; V3 that tests
  rate limiting must turn it back on for that scenario.
- `TELEMETRY_EXPORT_*` on with a 5 s scheduler — so the down-collector observation is real.
- `NOTIFICATIONS_ENABLED=false`, `MODEL_DEFAULT_PROVIDER=MOCK` — hermetic (no SMTP, no live model).
- `ENCRYPTION_KEY_ALLOW_BOOTSTRAP` is `false` in the env file and only overridden for the bootstrap command.

## V2.1 — wrapped mode (the isolation boundary; use this for anything adversarial)

```
python lab/wrapper/wrap_up.py --proof --baseline   # build images (first time ~3 min), start inside the
                                                    # internal network, run the 6 boundary proofs with and
                                                    # without ACT, run the V2 baseline in the runner
python lab/wrapper/wrap_down.py                     # remove containers, network, keys, run dir; verify no residue
```
On a completely clean host run `docker compose -f lab/wrapper/docker-compose.wrapped.yml build act`
before `build runner` (DG-7: the runner image is FROM the ACT image and compose builds in parallel).
Host mode (`lab/harness/lab_up.py`) is unchanged and was regression-run after V2.1
(`evidence/wrapped/hostmode_regression.log`: 17.7 s, 0 findings). Services choose their bind address
from `LAB_BIND` (loopback in host mode, all interfaces of the internal network in wrapped mode); the
harness reads endpoints from `LAB_MODE`, `ACT_BASE`, `LAB_DB_HOST/PORT`, `LAB_REGISTRY_HOST`,
`LAB_CANARY_HOST`, `LAB_MCP_HOST`, `LAB_BACKEND_DIR`, `LAB_ENV_FILE` (defaults = host mode).

## Known documentation gaps found while building (each is a manual/undocumented step made explicit)

- DG-1 host-level outbound isolation is not enforced by the lab (loopback binding + allowlists only).
- DG-2 POSIX paths in the harness are untested (Windows-only verification).
- DG-3 the venv launcher PID ≠ listener PID on Windows: `lab_down.py` and `collector_down_check.py` kill by port; documented here because a naive PID kill leaves listeners alive.
- DG-4 the email validator rejects `.invalid` addresses; the harness uses `@example.com` synthetic accounts.
