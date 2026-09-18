# ACT VALIDATION GATE — V2 LAB REPORT (2026-09-19)

Branch `validation/v2-lab` off `d398748` (V1 accepted; backend unchanged since `2b4f57b`). Artifacts in
this directory; the lab itself is `lab/`.

## A. Executive verdict

The lab exists, is disposable, rebuilds unattended from committed artifacts in about a minute, and
ACT governs the three Wave-1 agents at Tier 0–2 exactly as its own rulings say it should: discovered,
reconciled once, shadow-with-evidence, claimable to REGISTERED, GATEWAY_ENFORCED at the boundary,
GOVERNED unreachable (six refusals with the V0.2 code), containment truthfully REFUSED with grant
revocation genuinely effective, one tenant blind to the other, twelve expected audit events present,
zero unexpected canary appearances. No ACT code was changed; no adversarial scenario was fired. The
verdict is **CONDITIONAL** for two honest reasons that are prerequisites for V3 rather than V2 defects:
(1) host-level network isolation is not enforced by the lab on a developer machine (DG-1) — V3's
first adversarial scenario needs a VM or network-namespace wrapper; (2) ACT's telemetry export was not
exercised because V2 ran no native execution (OTLP baseline is empty, DG-5).

## B. Starting branch / commit

`validation/v1-threat-intel` tip `d398748` verified (= origin); `main` = `9667707`; worktree clean;
`validation/v2-lab` created from it. Docker 29.6.1 available; dev API (8000) and dev Postgres (5432)
left untouched.

## C. Lab architecture as built + isolation proof

See `LAB_ARCHITECTURE.md`. Fourteen lab listeners, all `127.0.0.1`; none non-loopback; the lab Postgres
published only on `127.0.0.1:5433`; dedicated `act_lab` database (never the shared dev DB); lab key
material bootstrapped into it with new fingerprints on every build; production `backend/.keys/` and
`backend/.env` never referenced. Limit DG-1 stated plainly.

## D. Wave-1 agents

Three separate OS processes (Python, Node, Python MCP client), each proven independent (AST imports /
`require()` list contain nothing from `app` or `backend`), each at Tier 2 ceiling: T1 read-only lab
data, T2 one governed write through ACT's gateway. Full per-agent record in `AGENT_MATRIX.md`.
Expected vs observed control state: **no divergence** for any agent.

## E. Canary instrumentation + baseline-zero scan

19 canaries (11 tokens, 5 fake PII rows, 3 fake credentials) planted in agent configs, MCP config,
the payroll DB, the object store, mailbox, finance tool, metadata decoy and attacker-sim before any
agent ran. Scan over every text/JSON column of every `act_lab` table, ACT's log and OTLP payloads:
**0 unexpected appearances**; the only hits are the grant-label token ACT is required to store (6 rows,
serving as the scan's positive control). `CANARY_REGISTER.md`.

## F. Discovery & reconciliation

First sweep created 3 agents (registry contacted over the socket, 2 requests logged), 364.5 ms; second
sweep created 0 and linked 3, 338.6 ms; exactly 3 canonical rows, 0 duplicates, no ambiguity finding
needed.

## G. Truthful control-state observations

All three: DISCOVERED / EXTERNAL / unowned on landing; GOVERNED requested before claim and after
REGISTERED → 409 `CONTROL_STATE_ORIGIN_INCOMPATIBLE` every time (6/6), audited as
`RUNTIME_AGENT_CONTROL_STATE_REJECTED`. Divergences: none.

## H. Truthful containment

`SUSPEND_AGENT` on the Python agent → `REFUSED`, reason "ACT has no enforcement authority over this
agent (control_state='REGISTERED', requires 'GOVERNED')…", no authority row — a PASS. Grant revocation
→ 200; the agent's next signed call → 403 and the canary finance tool received nothing further
(3 dispatches before, 3 after).

## I. Posture / shadow

All three shadow with conditions `discovered_outside_lifecycle` and `unmanaged_external_agent`; open
findings also `no_accountable_owner`, and `dangerous_dependency` for the MCP-linked agent. Finding
precision 3/3; no false positives.

## J. Dependency graph + blast radius

Python agent → trusted MCP-backed tool → canary payroll resource wired through the graph API;
`agents-reaching(payroll)` returned exactly the Python agent in 37.7 ms.

## K. Tenant isolation

Tenant B: 0 of A's agents in its inventory; 404 on all three enforcement-mode lookups.

## L. Telemetry / audit + canary scan

12/12 expected audit event types present, 0 missing. Canary scan zero (E). OTLP: the collector received
0 batches because ACT exports execution spans and V2 ran no native execution; with the collector
killed (verified by port) a governed call still returned 200 ALLOWED/DISPATCHED with 0 tracebacks.

## M. M4.11 lab-key behaviour

`keys verify` with lab keys rc 0; with the key paths pointed at a missing directory rc 1 and the
fail-loud message ("do NOT start the platform with a fresh key…"); `keys status` EXISTING_INSTALL with
the marker present; no key material in any output; each rebuild minted a different lab identity;
production identity untouched.

## N. MCP observability baseline (G-3)

Five servers built (trusted, unknown, risky, impersonator, rug-pull) plus the inert STDIO artifact; the
trusted one registered. ACT recorded only operator-declared fields (name, provenance, trust, version,
endpoint, declared capabilities) and never probed the server. Not captured: tool description text,
description hash/version pin, transport type, auth requirement, post-approval change, name collision
with an unregistered server, declared-vs-advertised reconciliation. `MCP_OBSERVABILITY_BASELINE.md`.
Nothing fired.

## O. Baseline measurements

time-to-discover 364.5 ms · time-to-reconcile 338.6 ms · reconciliation precision 3/3, 0 duplicates ·
posture evaluate 207.8 ms · finding precision 3/3 · blast-radius latency 37.7 ms · governed-call round
trip 322–411 ms · false positives/negatives 0/0 · canary appearances 0. First build within ±100 ms.

## P. Reproducibility proof

Teardown left 0 listeners, 0 containers, no run/keys directories; unattended rebuild in 18.4 s
(68.1 s first build with image pull); baseline reran with 0 findings; collector-down check passed.
Six documentation gaps recorded and handled. `REPRODUCIBILITY_PROOF.md`.

## Q. Defects / findings

| DEFECT | SEVERITY | PRE-EXISTING / INTRODUCED | ROOT CAUSE | IMPACT | FIX / DEFER | EVIDENCE |
|---|---|---|---|---|---|---|
| OB-1 assurance `ACT.COST.GOVERNED` returns FAIL for an external agent ACT does not run | Low (observation; may be an over-claim of knowledge — INSUFFICIENT_EVIDENCE is arguably the truthful result) | Pre-existing (5.9) | the control evaluates budget rows without asking whether ACT runs the agent | a compliance reader could read FAIL as "ungoverned" for something ACT cannot govern | DEFER — recorded for architecture review, no code change | `evidence/v2_baseline.json` assurance_python_agent |
| G-3 (confirmed live) MCP inventory captures nothing from the server itself | High for V3 | Pre-existing (5.4) | operator-declared model, no probe | rug pull / poisoning / STDIO invisible | DEFER (V1 O-3) | `MCP_OBSERVABILITY_BASELINE.md` |
| DG-1 lab host isolation not enforced | Medium (lab, not ACT) | Introduced by the dev-host choice | no VM/netns | V3 must not fire adversarial scenarios on an un-isolated host | DEFER — V3 prerequisite | `LAB_ARCHITECTURE.md` |
| DG-5 OTLP export unexercised | Low (lab coverage) | — | no native execution in Tier 0–2 | export/down-collector path only partially observed | DEFER to V3+ | `BASELINE_OBSERVATIONS.md` §9 |
| DG-3/DG-6 harness self-matches (PID kill, comment string match, grant-label hit) | Low (lab tooling) | Introduced in V2, fixed in V2 | naive checks | none on ACT | FIXED in `lab/harness` | `REPRODUCIBILITY_PROOF.md` |

No ACT product defect was found in V2; no P0.

## R. Artifacts committed

`docs/validation/v2/`: LAB_ARCHITECTURE.md, LAB_BUILD.md, AGENT_MATRIX.md, CANARY_REGISTER.md,
BASELINE_OBSERVATIONS.md, MCP_OBSERVABILITY_BASELINE.md, REPRODUCIBILITY_PROOF.md, V2_REPORT.md,
`evidence/` (v2_baseline.json, collector_down.json, build_log.json, canaries.json, rebuild_chain.log,
lab_up_first.log, v2_baseline_console.txt). `lab/`: compose, initdb, env, canaries, services, mcp,
agents, adversary (idle), harness. `.gitignore`: `lab/run/`, `lab/.keys/`. No secrets (all lab values
synthetic; canary tokens recorded as such).

## S. Git status

Committed on `validation/v2-lab`, pushed; `main` untouched at `9667707`; not merged.

## T. V3 readiness

The lab can now support: discovery/reconciliation/posture/graph/containment observation of external
agents over real sockets; three independent agents at T0–T2 with a governed boundary; five MCP-shaped
servers with measurable description hashes (rug-pull and impersonation variants ready but gated);
canary targets with a zero baseline; unattended rebuild. It cannot yet support: adversarial execution
on this host (DG-1); Tier 3+ agent capability; cloud-platform discovery (I-4); telemetry-export
attacks (DG-5); anything requiring an ACT code change.

**VERDICT: V2 CONDITIONAL — REVIEW REQUIRED**
