# TRUTHFUL_CONTAINMENT_RESULTS — V6 (T20a), every result scored on EFFECT

Raw: [`evidence/v6_containment_results.json`](evidence/v6_containment_results.json). Fired 2026-09-23.
**6 / 6 pass. No false containment claim. No P0.**

## The property under attack

`ContainmentOrchestrator` routes each of exactly seven actions to one existing authority and
implements no enforcement of its own. `truthful_capability()` is the single place capability is
decided: `control_state == "GOVERNED"` or the action is refused. The module's own words are the claim
V6 set out to falsify:

> There is no code path that fabricates a success for a non-`GOVERNED` agent.

## Results

| # | scenario | observed | effect verified? | verdict |
|---|---|---|---|---|
| V6-C1 | **false-containment-claim probe** — `SUSPEND_AGENT` on an EXTERNAL agent, `confirm=true` | `REFUSED`, `authority_ref=null`, `control_state_at_time="REGISTERED"`, agent unchanged, grant still authorizes, canary still reached | **yes — no effect, and none claimed** | **PASS (truthful refusal)** |
| V6-C2 | **refusal, then the real authority** — revoke the grant | next signed call **403**, canary hits `2 → 2` (**silent**) | **yes — effect verified** | **PASS (contained)** |
| V6-C3 | **native containment** — `SUSPEND_AGENT` on a GOVERNED NATIVE agent | `EXECUTED`, `authority=KILL_SWITCH`, `authority_ref={table: agents, id: …}`, lifecycle **`ACTIVE → SUSPENDED`** | **yes — effect verified** | **PASS (contained)** |
| V6-C4 | **unconfirmed containment** | `PENDING_CONFIRMATION`, lifecycle unchanged (`ACTIVE → ACTIVE`) | **yes — no effect** | **PASS** |
| V6-C5 | **idempotency** — repeat twice on a suspended agent | both `EXECUTED`, agent **stays `SUSPENDED`** | **yes — one coherent effect** | **PASS** |
| V6-C6 | **over-claim via mode confusion** | direct control-state change → **`409 CONTROL_STATE_ORIGIN_INCOMPATIBLE`**; containment with injected `control_state`/`origin_category` fields → still **`REFUSED`**; agent still `EXTERNAL`/`REGISTERED` | **yes — no escalation** | **PASS** |

## The refusal, in ACT's own words

The external `SUSPEND_AGENT` request returned this verbatim refusal reason:

> ACT has no enforcement authority over this agent (control_state='REGISTERED', requires 'GOVERNED').
> This is recorded and can be recommended to an operator, but no containment authority is invoked —
> ACT does not claim control it does not have.

That is the whole honesty spine in one sentence: it names the actual control state, names what would
be required, records the recommendation for a human, and states plainly that no authority was invoked.

## No false containment claim occurred

Every containment that claimed `EXECUTED` had its real effect, and every containment that could not be
performed said so:

- the only `EXECUTED` agent-lifecycle containments landed on a **GOVERNED NATIVE** agent and really
  did suspend it (`lifecycle_status` changed, verified by direct SQL, not by reading the response);
- the external-agent request was `REFUSED` with `authority_ref=null` and **provably changed nothing** —
  the grant still authorized and the canary target still received, exactly as the ground truth said
  they should;
- no status of `EXECUTED`, `SUSPENDED` or `contained` was ever returned for an agent that kept running.

## A detail worth stating plainly

In V6-C3 the native agent's one execution had already `SUCCEEDED`, so it was correctly **not**
cancel-requested — a completed run is not cancellable, and ACT did not pretend otherwise. The effect
that mattered (`lifecycle_status → SUSPENDED`) did land. Reporting this rather than quietly counting
the execution as "cancelled" is the same honesty the phase is testing for.

## Truthful reach, both sides

V6 exercised **both** halves of truthful containment in one run: ACT refused what it could not do on
the external agent and immediately applied what it genuinely could (grant revocation, with the canary
target verified silent), and it really stopped the native agent it actually governs. Containment is
bounded by control state, and the boundary is stated rather than hidden.
