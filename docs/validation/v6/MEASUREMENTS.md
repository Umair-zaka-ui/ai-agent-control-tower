# MEASUREMENTS — V6: detection vs containment-effect vs refusal-truthfulness

Raw: [`evidence/v6_measurements.json`](evidence/v6_measurements.json). The three axes are reported
separately and never merged into one number, because ACT deliberately behaves differently on each.

## Containment effect (the P0 axis)

| metric | required | observed |
|---|---|---|
| **containment effect-verification rate** — claimed vs real effect | every claim verified | **every containment scored on effect; false claims: 0** |
| **false containment claims** | 0 | **0** |
| claimed `EXECUTED` actions whose real effect was verified | all | **all** (native suspend: `ACTIVE → SUSPENDED`; grant revocation: `403` + canary silent) |
| unconfirmed containment causing an effect | 0 | **0** (`PENDING_CONFIRMATION`, lifecycle unchanged) |
| over-claim via mode confusion | 0 | **0** (`409 CONTROL_STATE_ORIGIN_INCOMPATIBLE`) |
| containment idempotency (repeat leaves one coherent effect) | yes | **yes** (stays `SUSPENDED`) |
| **false-positive containment** (an over-eager stop of a benign agent) | 0 | **0** |

## Refusal truthfulness

| metric | observed |
|---|---|
| **truthful-refusal rate** | **1 / 1** — external `SUSPEND_AGENT` refused with a real reason, then the authority ACT genuinely holds was applied |
| refusal names the actual control state and what would be required | **yes** (`control_state='REGISTERED', requires 'GOVERNED'`) |
| refusal carries no `authority_ref` | **yes** (`null`) |
| **revocation effectiveness** | **`403` + canary target silent** (hits `2 → 2`) |

## Kill-switch and enforcement-path integrity

| metric | required | observed |
|---|---|---|
| **kill-switch dominance under race** | 100 % | **100 %** — kill never undone |
| reactivation path reachable by automation | none | **none** (0 reactivation statements in the threat package) |
| killed execution resurrectable | no | **no** (`409 INVALID_LIFECYCLE_TRANSITION`) |
| revert of a kill-switch action | refused | **refused** (`409 CONTAINMENT_ACTION_NOT_REVERSIBLE`) |
| revocation window where a revoked grant still authorizes | none | **none** (`[200,200,403,403,403,403]`, no allow after denial) |
| **one enforcement path holds** | yes | **yes** — 0 in-package enforcement writes; 8/8 executed actions attributed to an authority with an `authority_ref` |
| **fail-closed on mandatory containment** | yes | **yes** — `FAILED` with the real error, never a silent `EXECUTED` |
| concurrent containments causing a 5xx or torn state | 0 | **0** (one honest `FAILED` among three) |

## Detection (a separate axis — signals, not enforcement)

| metric | observed |
|---|---|
| deterministic rules shipped | **6** |
| governance-denial spike detected for an **external** agent after 12 denials | **no — 0 findings** (structural: the rule joins `agent_executions`, which external agents never produce) |
| prompt injection detected | **no** — documented evidence gap, confirmed |
| detection blocking an execution (fail-open check) | **never** |
| a finding enforcing anything by itself | **never** |

## Pass counts

| batch | pass / total |
|---|---|
| T20a truthful containment | **6 / 6** |
| T20b kill-switch + races | **6 / 6** |
| T21 one path + fail-closed | **4 / 4** |
| T16 detection | **2 / 4** (2 recorded GAPs, 0 failures) |
| **total** | **18 / 20**, with the 2 non-passes being recorded detection gaps |

**Canary escapes: 0.** ACT log 320 lines, 0 canary markers, 0 tracebacks. **All five P0 flags false.**

## Baseline comparison

| | V3 | V4 | V5 | V6 |
|---|---|---|---|---|
| canary escapes | 0 | 0 | 0 | **0** |
| the phase's split | contained **but not detected** | held **but not observable** | picture true **and** bounded | **contains truthfully — and says so when it cannot** |
| detection posture | injection not detected | — | — | **narrower than expected for external agents (F6-1)** |

V6's headline is not a rate but a property: across every containment attempted, **the status always
matched the effect**. Latency is unchanged from baseline; containment decisions are synchronous ORM
writes with no external I/O.
