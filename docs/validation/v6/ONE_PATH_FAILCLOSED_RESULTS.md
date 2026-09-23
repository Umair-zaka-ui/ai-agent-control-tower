# ONE_PATH_FAILCLOSED_RESULTS — V6 (T21): one enforcement path, and both failure directions

Raw: [`evidence/v6_onepath_results.json`](evidence/v6_onepath_results.json). Fired 2026-09-23.
**4 / 4 pass. No parallel enforcement path. Fail-closed on mandatory containment and fail-open on
detection both proven in the same run.**

| # | scenario | observed | verdict |
|---|---|---|---|
| V6-P1 | **one enforcement path (AST)** — parse the threat package for enforcement it performs itself | **zero** direct writes to an agent's `lifecycle_status`, an execution's `cancel_requested`, or a deployment's `status`, across all 7 modules (`__init__`, `containment`, `evaluator`, `lifecycle`, `routes`, `rules`, `schemas`) | **PASS (no enforcement implemented)** |
| V6-P2 | **no unattributed enforcement** — inspect every containment that claimed `EXECUTED` | **8** executed actions, all naming an authority (`KILL_SWITCH`, `GOVERNANCE_POLICY`) and all carrying an `authority_ref`; **0 unattributed** | **PASS (all attributed)** |
| V6-P3 | **fail-CLOSED on mandatory containment** — force an authority that cannot complete | status **`FAILED`** with `{"error": "Tool assignment not found.", "error_class": "IdentityError"}`; **not** silently executed | **PASS (failed-closed)** |
| V6-P4 | **detection fails OPEN** — evaluate, then exercise the agent | evaluation `200`; the agent's granted call still `200`; **execution not blocked by detection** | **PASS (fails open)** |

## One path, verified two ways

**Structurally (P1):** the threat package writes no enforcement state of its own. Every containment
reaches one of the seven mapped authorities — `KillSwitchService`, `ToolRegistryService.revoke`,
`CapabilityService.revoke`, `revoke_key`, `ConnectorService.disable`, `GovernancePolicyService.create`
— and there is no eighth action and no in-package enforcer.

**Behaviourally (P2):** every containment that actually claimed `EXECUTED` in this run named its
authority and carried an `authority_ref` pointing at the real row the authority touched. Nothing
stopped an agent outside an existing authority, so **no attack induced a parallel enforcement path**.

## Both failure directions, in one run

This is the property M4.3 established and V6 re-proved under attack — the two directions must be
opposite, and both were observed:

- **Mandatory containment fails CLOSED.** Pointing `DENY_TOOL` at a tool assignment that does not
  exist made the authority raise. The action was recorded **`FAILED`** with the real error and error
  class. It was not silently marked `EXECUTED`, and it was not silently passed over. A containment
  that cannot complete says so.
- **Detection fails OPEN.** Running a threat evaluation neither blocked nor degraded the agent: its
  granted capability still returned `200` immediately afterwards. A detection pass is a signal, and a
  signal never gates execution.

Getting these backwards in either direction would be a serious defect — a silently-passing mandatory
containment would be a false containment claim, and a detection failure that blocked execution would
turn an observability plane into an unreviewed enforcer. Neither occurred.
