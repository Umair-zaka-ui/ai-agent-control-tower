# REBASELINE — V2 §6 observations inside the wrapper vs the V2 host-mode table (V2.1)

Source: `evidence/wrapped/v2_baseline_wrapped_A.json` (rebuild A) and `_B.json` (rebuild B). Same
harness (`lab/harness/v2_baseline.py`), same observations; only endpoints changed (in-network names).

## Behaviours (all three Wave-1 agents, both rebuilds)

| observation | V2 host mode | wrapped A | wrapped B | holds? |
|---|---|---|---|---|
| discovery: agents created on first sweep | 3 (registry contacted) | 3 (3 registry requests logged) | 3 | yes |
| reconciliation: second sweep created / linked; canonical rows; duplicates | 0 / 3; 3; 0 | 0 / 3; 3; 0 | 0 / 3; 3; 0 | yes |
| landing state | DISCOVERED / EXTERNAL / unowned | same | same | yes |
| **GOVERNED refused** (before claim + after REGISTERED) | 6/6 → 409 `CONTROL_STATE_ORIGIN_INCOMPATIBLE` | 6/6 | 6/6 | yes |
| GATEWAY_ENFORCED affordances | `reaches_agent_execution=false`, display "authorizes … through ACT's gateway" | same | same | yes |
| T2 governed call: allowed / forbidden (python, node) | 200 ALLOWED+DISPATCHED / 403 DENIED | same | same | yes |
| MCP client T1 (`initialize`, `tools/list`, `tools/call`) + T2 allowed | ok / 200 | ok / 200 (after the first-attempt token-rotation fix) | ok / 200 | yes |
| **containment**: SUSPEND_AGENT → REFUSED, reason, no authority row | yes | 201 REFUSED, `authority_ref=null` | same | yes |
| **grant revocation effective**: next call 403, further dispatches to canary finance | 403, 0 | 403, 0 | 403, 0 | yes |
| posture/shadow with conditions | 3/3 shadow, `discovered_outside_lifecycle` + `unmanaged_external_agent`; `no_accountable_owner`, `dangerous_dependency` open | same | same | yes |
| blast radius to canary payroll | exactly the Python agent | same | same | yes |
| tenant isolation | B sees 0; 404 ×3 | 0; 404 ×3 | 0; 404 ×3 | yes |
| audit events (12 expected) | 12/12 | 12/12 | 12/12 | yes |
| **canary scan** | 0 unexpected; grant-label positive control fires (6 rows) | 0 unexpected; positive control fires | same | yes |
| ACT log canary marker hits / tracebacks | 0 / 0 | 0 / 0 | 0 / 0 | yes |
| M4.11: verify with lab keys / with missing key path | rc 0 / rc 1 (fail-loud) | 0 / 1 | 0 / 1 | yes |
| assurance for the Python agent | 9 PASS, 2 INSUFFICIENT_EVIDENCE, `ACT.COST.GOVERNED` FAIL (OB-1) | identical | identical | yes (OB-1 unchanged) |

## Measurements

| metric | V2 host (rebuilt) | V2 host (first) | wrapped A | wrapped B | divergence? |
|---|---|---|---|---|---|
| time-to-discover (3 agents) | 364.5 ms | 427.6 ms | **119.7 ms** | 127.8 ms | faster — see note |
| time-to-reconcile | 338.6 ms | 260.0 ms | **84.3 ms** | 84.4 ms | faster |
| reconciliation precision | 3/3, 0 dup | 3/3, 0 | 3/3, 0 | 3/3, 0 | none |
| posture evaluate | 207.8 ms | 224.0 ms | 160.8 ms | 202.2 ms | none material |
| finding precision (shadow) | 3/3 | 3/3 | 3/3 | 3/3 | none |
| blast-radius latency | 37.7 ms | 34.9 ms | 26.1 ms | 24.3 ms | faster |
| governed-call round trip incl. agent process start | 322–411 ms | 386–411 ms | 182–277 ms | similar | faster |
| FP / FN | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | none |
| canary unexpected appearances | 0 | 0 | 0 | 0 | none |

**Note on the faster numbers.** The wrapped lab is *faster*, not slower: in host mode every hop traversed
the Windows loopback stack and a Docker Desktop port-forward to Postgres (5433 → VM), whereas inside
the wrapper ACT, Postgres, the registry and the agents share one Linux bridge in the Docker VM and the
harness itself runs there. This is a latency-floor change from topology, not a behaviour change:
every count, status code, error code, refusal reason, audit set and canary result is identical. No
material divergence; the wrapper changed isolation, not behaviour.
