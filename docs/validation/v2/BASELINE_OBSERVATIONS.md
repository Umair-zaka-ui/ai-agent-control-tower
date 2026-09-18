# BASELINE_OBSERVATIONS — §6 results with measurements (V2, rebuilt lab `07a88edd`, 2026-09-19)

Source: `evidence/v2_baseline.json` (rebuilt lab) and `evidence/collector_down.json`; the first build's
run (`evidence/lab_up_first.log`, console in `evidence/v2_baseline_console.txt` from build `b54de795`)
gave the same observations with timings within ±100 ms. Nothing was attacked; every step is a normal,
authorized API call or an agent's normal Tier 0–2 behaviour.

| # | observation | expected | observed | measurement |
|---|---|---|---|---|
| 1 | Discovery over a real socket | 3 agents created from the lab registry; registry actually contacted | first sweep: `agents_created=3, agents_linked=0, status=SUCCEEDED`; registry logged 2 GET `/agents` requests (page + terminal empty page) | **time-to-discover 364.5 ms** (first build 427.6 ms) |
| 2 | Reconciliation: no duplicate, no silent merge | second sweep creates 0, links 3; exactly 3 canonical rows | `agents_created=0, agents_linked=3`; 3 rows, 0 duplicate `external_reference` | **time-to-reconcile 338.6 ms** (260.0); **reconciliation precision 3/3, duplicates 0** |
| 3 | Truthful control state | each lands DISCOVERED, non-NATIVE, unowned; GOVERNED unreachable | all three: `control_state=DISCOVERED, origin_category=EXTERNAL, owner=None`; `POST control-state GOVERNED` → **409 `CONTROL_STATE_ORIGIN_INCOMPATIBLE`** for all three, both before claim and again after REGISTERED | 6/6 GOVERNED attempts refused |
| 4 | Truthful affordances | GATEWAY agents labelled "authorize boundary calls", never "govern"; `reaches_agent_execution=false` | 5.7 mode: `GATEWAY_ENFORCED`, `reaches_boundary_calls=true`, `reaches_agent_execution=false`, display "ACT authorizes this agent's capability calls that route through ACT's gateway."; command center rows identical (server-authoritative affordances) | 3/3 |
| 5 | Truthful containment | SUSPEND_AGENT REFUSED with the truthful reason; grant revocation works | `SUSPEND_AGENT` → HTTP 201, `status=REFUSED`, reason "ACT has no enforcement authority over this agent (control_state='REGISTERED', requires 'GOVERNED')…", `authority_ref=null`; revoke → 200; the Python agent's next governed call → **403**; canary finance received **0** further dispatches (3 before) | refusal + real revocation both as expected |
| 5a | Wave-1 agents at T0–T2 | each runs in its own process; T2 allowed call dispatched, forbidden denied | python: allowed 200 `ALLOWED/DISPATCHED`, forbidden 403 `DENIED/NOT_DISPATCHED`; node: same; mcp client: MCP `initialize`/`tools/list` (`payroll_read`)/`tools/call` ok, allowed 200 dispatched. Canary finance recorded exactly 3 dispatches; attacker-sim received **0** requests | agent run times 322–411 ms |
| 6 | Posture / shadow | unowned discovered agents are shadow, with conditions naming evidence | all three `shadow=true` with conditions `discovered_outside_lifecycle`, `unmanaged_external_agent`; open findings also include `no_accountable_owner` and, for the MCP-linked agent, `dangerous_dependency` | **finding precision 3/3 expected shadow**; posture evaluate 207.8 ms |
| 7 | Dependency graph + blast radius | the Python agent, and only it, reaches the canary payroll resource via the MCP-backed tool | `agents-reaching(RESOURCE=canary payroll)` = {python agent}, count 1 | **blast-radius latency 37.7 ms** (34.9) |
| 8 | Tenant isolation | tenant B sees none of A's estate | tenant B's command-center inventory contains none of the 3 ids; enforcement-mode lookups → 404, 404, 404 | 0 leaks |
| 9 | Telemetry / audit + canary scan | every step audited; zero canary appearances | audit events present: DISCOVERY_RUN_STARTED, POSTURE_EVALUATED, RUNTIME_AGENT_CLAIMED, RUNTIME_AGENT_CONTROL_STATE_CHANGED, RUNTIME_AGENT_CONTROL_STATE_REJECTED, EXTERNAL_ENFORCEMENT_MODE_CHANGED, EXTERNAL_GRANT_ISSUED, EXTERNAL_GATEWAY_CALL_ALLOWED, EXTERNAL_GATEWAY_CALL_DENIED, EXTERNAL_GRANT_REVOKED, CONTAINMENT_ACTION_REFUSED, ASSURANCE_EVALUATED (12/12 expected, 0 missing). Canary scan: 0 unexpected hits (see CANARY_REGISTER). **OTLP export: 0 batches** — ACT's exporter only ships execution spans and V2 ran no native execution, so the collector saw nothing; `collector_down_check` still proved a governed call is served with the collector down (200 ALLOWED/DISPATCHED, 0 tracebacks) | audit 12/12; canary 0 |
| 10 | M4.11 lab keys | fail-loud with missing keys; no identity change; no material printed | `keys verify` with lab keys → rc 0; with the key paths pointed at a non-existent directory → rc 1 with "no provider-credential encryption key is available — restore … do NOT start the platform with a fresh key"; `keys status`: `EXISTING_INSTALL (bootstrap marker present)`, signed-state tables `signing_keys`; no `BEGIN PRIVATE KEY` / Fernet token in any output; production `backend/.keys/` untouched | fail-loud confirmed |

## Assurance observation (step 12 of the 5.10 shape)

For the Python agent after claim/registration: OWNERSHIP, PROVENANCE, GOVERNANCE.POLICY_COVERAGE,
RELIABILITY.SLO_COVERAGE, CREDENTIAL.LIFECYCLE, SUPPLY_CHAIN.MCP_TRUST, TOOL.LEAST_PRIVILEGE,
MODEL.APPROVED, INCIDENT.RECONSTRUCTABLE → PASS; RUNTIME.TRACEABLE and AUTHORITY.CHAIN_PROVABLE →
INSUFFICIENT_EVIDENCE; **COST.GOVERNED → FAIL**. The last is recorded as observation OB-1 (see
V2_REPORT §Q): for an agent ACT does not run there is no cost ledger, so FAIL rather than
INSUFFICIENT_EVIDENCE may itself be an over-claim of knowledge. Not a V2 blocker; not changed.

## Baseline numbers V3+ compares against

| metric | value (rebuilt lab) | first build |
|---|---|---|
| time-to-discover (3 agents, real socket) | 364.5 ms | 427.6 ms |
| time-to-reconcile (second sweep) | 338.6 ms | 260.0 ms |
| reconciliation precision | 3/3, 0 duplicates | 3/3, 0 |
| posture evaluate (tenant) | 207.8 ms | 224.0 ms |
| finding precision (shadow) | 3/3 | 3/3 |
| blast-radius latency (canary payroll) | 37.7 ms | 34.9 ms |
| governed-call round trip incl. agent process start | 322–411 ms | 386–411 ms |
| false positives / negatives | 0 / 0 across the ten observations | 0 / 0 |
| canary appearances in ACT | 0 unexpected | 0 unexpected |
