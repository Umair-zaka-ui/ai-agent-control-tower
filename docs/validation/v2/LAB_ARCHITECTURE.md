# LAB_ARCHITECTURE — as built (V2, 2026-09-19)

ACT is the system under test, never the sandbox. Everything below is lab-owned, disposable, and bound
to loopback. Built from `lab/` (committed) by `lab/harness/lab_up.py`; destroyed by `lab_down.py`.

## Topology (as built on the Windows 11 dev host)

| Zone | Component | Where it runs | Bind | Purpose |
|---|---|---|---|---|
| ACT under test | backend (uvicorn) | host process, ACT's own venv, cwd `backend/` | 127.0.0.1:8802 | the instrument's target; lab env only (`lab/env/act-lab.env`) |
| ACT under test | PostgreSQL 17 `act_lab` | Docker `postgres:17-alpine` (`act_lab_postgres`), no volume | 127.0.0.1:5433 | **dedicated lab DB** — never the shared dev DB (V0 W-6) |
| ACT under test | workers/scheduler | in-process (uvicorn lifespan; telemetry export scheduler on, 5 s) | — | |
| ACT under test | LAB key material | `lab/.keys/` (git-ignored), bootstrapped into the empty `act_lab` by `keys bootstrap` with the gate on for that one command | — | never production `backend/.keys/` |
| External agent zone | Python agent · Node agent · MCP client | three separate OS processes (`python`, `node`, `python`) | clients only | Wave-1, Tier 0–2; AST/require-asserted to import nothing from `app` |
| Inbound discovery | lab agent registry | host process `lab/services/registry.py` | 127.0.0.1:8811 | 5.2 `HTTP_AGENT_REGISTRY` shape; records every fetch |
| MCP zone | trusted · unknown · risky · impersonator · rug-pull | five host processes `lab/mcp/mcp_server.py <variant>` | 127.0.0.1:8831–8835 | MCP-shaped JSON-RPC (initialize / tools/list / tools/call) over HTTP; `/manifest` exposes the description hash; **built, not fired** |
| MCP zone | STDIO variant | `lab/mcp/stdio_mcp_server.py` + `stdio_config.json` | none (never launched) | the V1 R-028/R-029 transport class, inert |
| Canary target zone | payroll DB `lab_payroll` | same Docker Postgres, second database | 127.0.0.1:5433 | 5 fake employees, each row canary-tagged |
| Canary target zone | object store · mailbox · finance tool · metadata decoy · attacker-sim | one host process `lab/services/canary_zone.py` | 127.0.0.1:8821–8825 | every response canary-tagged; finance records and never executes; attacker-sim logs all egress it receives |
| Adversary zone | code-exec sandbox · malicious-dependency registry · injection corpora host | `lab/adversary/README.md` — **provisioned as directories, idle** | none | nothing exercised in V2 |
| Observability | OTLP/HTTP collector (+ `--down` mode) | host process `lab/services/otlp_collector.py` | 127.0.0.1:8812 | ACT exports traces here (`TELEMETRY_EXPORT_*` in the lab env); evidence in `lab/run/otlp/*.jsonl` |
| Observability | evidence capture · result ledger | `lab/run/results/*.json`, `lab/run/logs/*.log`, `lab/run/canary_zone/*.jsonl` | — | copied into `docs/validation/v2/evidence/` per build |

## Isolation proof (captured from the live lab, 2026-09-19)

```
netstat -ano | LISTENING on lab ports:
127.0.0.1:5433  127.0.0.1:8802  127.0.0.1:8811  127.0.0.1:8812
127.0.0.1:8821  127.0.0.1:8822  127.0.0.1:8823  127.0.0.1:8824  127.0.0.1:8825
127.0.0.1:8831  127.0.0.1:8832  127.0.0.1:8833  127.0.0.1:8834  127.0.0.1:8835
non-loopback lab listeners: none
docker port act_lab_postgres: 5432/tcp -> 127.0.0.1:5433
```

- Every lab endpoint an agent or ACT can reach is `127.0.0.1`. ACT's HTTP tools carry
  `allowed_hosts: ["127.0.0.1"]` (M1 egress guard), so the only egress ACT will dispatch for a lab
  capability is to the canary finance tool; the attacker-sim endpoint exists as the destination a
  V3+ exfiltration attempt would have to reach, and in V2 it received nothing.
- The lab Postgres has no named volume; `docker compose down -v` leaves no data.
- **Honest limit:** this is a developer host, not a network-isolated VM. Outbound host-level egress is
  not firewalled by the lab; isolation rests on loopback binding plus ACT's egress allowlists. Recorded
  as documentation gap DG-1 in `REPRODUCIBILITY_PROOF.md`; a VM/network-namespace wrapper is the V3
  prerequisite before any adversarial scenario runs.

## Lab invariants (each demonstrable)

| invariant | how demonstrated |
|---|---|
| everything disposable and reproducible | `lab/` committed; `lab_down.py` then `lab_up.py` rebuilt the lab from scratch (`REPRODUCIBILITY_PROOF.md`) |
| synthetic secrets and fake PII only | `lab/env/act-lab.env` values are synthetic; `lab/canaries.py` generates all PII and credentials with the `ACTLAB-CANARY` marker |
| canary credentials detectably fake | shapes `sk-ACTLAB-…`, `AKIAACTLAB…`, `actlab_bearer_…`; the metadata decoy returns `LAB DECOY - detectably fake` |
| no route to a non-lab network | loopback binding above + egress allowlists; DG-1 for host-level firewalling |
| lab keys only | `SIGNING_KEY_PATH=../lab/.keys/`, `MODEL_CREDENTIAL_ENCRYPTION_KEY_PATH=../lab/.keys/model_credentials.key`; `keys status` reports the lab fingerprints; production `.keys/` untouched (git status clean) |
| rebuildable from scratch | §8 proof |
| ACT never modified to make anything pass | `git diff 2b4f57b -- backend/` is empty on this branch |

## What the ACT instance in the lab is

`validation/v2-lab` at the V1 tip (`d398748`), backend unchanged since `2b4f57b`; migrations at head
`0061_assurance_evidence` applied to the empty `act_lab`; frontend production build from V0 (`npm run
build` green) — the lab does not serve the SPA because no V2 observation needs a browser; the command
center is observed through its API, which is what the SPA renders from (5.8 server-authoritative affordances).
