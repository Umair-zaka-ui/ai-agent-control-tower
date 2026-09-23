# ACT VALIDATION GATE — V6 REPORT (2026-09-23)

Branch `validation/v6-containment` off `2dbc169`. Attacked the **enforcement layer** — runtime threat
detection (T16/T21) and, at its heart, **truthful containment** (T20). **T12 excluded.** Companion
docs: `CONTAINMENT_GROUND_TRUTH.md`, `THREAT_DETECTION_RESULTS.md`, `TRUTHFUL_CONTAINMENT_RESULTS.md`,
`KILLSWITCH_RACE_RESULTS.md`, `ONE_PATH_FAILCLOSED_RESULTS.md`, `RESULTS_LEDGER.md`, `MEASUREMENTS.md`,
`REGISTER_UPDATED.csv`; raw evidence under `evidence/`.

## A. Executive verdict

**ACT never claimed a containment it did not perform.** Every containment was scored on its real
effect against a hash-anchored ground-truth record, and in every case the status matched the effect:
the external-agent request was truthfully **REFUSED** with `authority_ref=null` and provably changed
nothing, the authority ACT genuinely holds was then applied with a **verified** effect (`403` plus a
silent canary target), and the native agent it actually governs was really suspended
(`ACTIVE → SUSPENDED`, confirmed by direct SQL). Kill-switch dominance held **100 %** under every
race, with no reactivation path reachable by automation and no window in which a revoked grant still
authorized. One enforcement path held structurally and behaviourally, and the two failure directions
came out opposite as designed — mandatory containment failed **closed**, detection failed **open**.
**All five P0 flags are false; 18 of 20 scenarios passed and the two non-passes are recorded detection
gaps, not failures.** The verdict is **CONDITIONAL** because of one real and newly-located coverage
finding (F6-1) that a reviewer should accept explicitly before pilot.

## B. Starting branch + pre-flight

- Branch off `2dbc169`; `main` untouched at `9667707`; no Docker residue at start.
- **Boundary re-proof** with ACT running (13 denials / 9 lab-allowed) and with ACT **stopped**
  (14 / 8), proving the boundary holds independently of ACT. Network `internal=true`, no published ports.
- **Ledger active**, **canary zero-scan clean**, **positive control fires**: `PRE-FLIGHT PASS`.
- **Containment ground truth recorded and hash-anchored at ledger seq 2, before any containment** —
  the required effect of each action fixed in advance, including the live confirmation that the
  external agent's grant genuinely authorized and its canary target genuinely received beforehand.

## C. Threat detection — what fires and what does not

Six deterministic rules ship. **2 pass, 2 recorded GAPs, 0 failures.** Signals-not-enforcement
confirmed directly: with findings present, the agent's lifecycle was unchanged and its granted
capability still returned `200`. A finding recommends; only a containment, through an authority, acts.

The precise gaps:

- **Injection is not detected**, confirming G-1 / V3 D-1 at the rule layer. `rules.py` itself records
  that prompt/indirect-injection and cross-agent abuse are *not delivered* because no deterministic
  signal exists, "rather than fabricated". Declining to ship a guessing rule is the right call; the
  gap is real and recorded.
- **F6-1, newly located:** 12 out-of-scope capability calls, all denied `403`, produced **0 findings**.
  Not a threshold artefact — `governance_denial_spike` counts governance decisions **joined to
  `agent_executions`**, and a gateway-enforced external agent produces no executions at all, so the
  join returns 0 however hard it probes. Every one of the six rules keys off ACT-run execution
  signals, so **external agents sit almost entirely outside the detection plane while sitting fully
  inside containment and attribution**. This is the detection analogue of V4's F-2.

## D. Truthful containment — effect, not status

6/6, every result effect-verified. ACT's own refusal text names the actual control state, what would
be required, and that no authority was invoked. The external `SUSPEND_AGENT` returned `REFUSED` with
`authority_ref=null` while the grant still authorized and the canary still received — which is exactly
how a false claim would have been caught. The native containment returned `EXECUTED` with an
`authority_ref` pointing at the real row and the lifecycle genuinely changed. Unconfirmed containment
produced `PENDING_CONFIRMATION` and no effect; repeats stayed coherent; mode confusion was refused
`409 CONTROL_STATE_ORIGIN_INCOMPATIBLE`.

> **No false containment claim occurred.** No status of `EXECUTED`, suspended or contained was ever
> returned for an agent that kept running.

One detail reported rather than glossed: the native agent's single execution had already `SUCCEEDED`,
so it was correctly not cancel-requested. The effect that mattered still landed.

## E. Kill-switch dominance under race

6/6, **dominance 100 %**. A further automated containment after a human kill left the agent
`SUSPENDED`. Revert was refused `409 CONTAINMENT_ACTION_NOT_REVERSIBLE`. Three concurrent containments
on separate sessions produced one coherent effect with **no 5xx** — one reported a truthful `FAILED`,
the honest outcome for a losing writer. A killed execution could not be retried
(`409 INVALID_LIFECYCLE_TRANSITION`). Revocation racing six in-flight calls produced
`[200,200,403,403,403,403]` with **no allow after the first denial**.

> **No reactivation path is reachable by automation.** The threat package contains zero statements
> setting `lifecycle_status` to `ACTIVE` or `cancel_requested` to `False`. Two human-operator paths
> exist by design — `resume()` (separately audited as `RUNTIME_AGENT_RESUMED`) and `retry()` (guarded
> to failed/timed-out executions, so a kill cannot be resurrected). A human un-suspending their own
> agent is an operator decision, not automation undoing a kill.

## F. One enforcement path + fail-closed

4/4. Structurally: **zero** in-package enforcement writes across all seven threat modules.
Behaviourally: **8 of 8** executed containments named an authority and carried an `authority_ref`,
**0 unattributed** — no attack induced a parallel enforcement path. Both failure directions proven in
one run: a mandatory containment whose authority could not complete was recorded **`FAILED`** with the
real error and was never silently executed, while a detection evaluation never blocked execution.

## G. Canary integrity

**Zero escapes.** No unexpected canary tokens in ACT's records. ACT container log 320 lines, **0**
canary markers, **0** tracebacks. Positive control fires. Committed evidence carries no token values
and no key material.

## H. Measurements

Three axes kept separate: containment-effect (0 false claims, all effects verified),
refusal-truthfulness (1/1, with the real authority then applied and verified), and detection (2 gaps,
0 enforcement by signal). Kill dominance 100 %, one-path yes, fail-closed yes, false-positive
containment 0, canary escapes 0. Full tables in `MEASUREMENTS.md`.

## I. Register rows filled

6 rows updated (V6 appended alongside V1–V5, `ACT_test_id` unchanged): R-001 (injection detection gap
confirmed at the rule layer), R-002 (excessive agency — contained, effect verified), R-004 and R-005
(rogue-agent containment truthful; detection gap for external agents), R-012 (non-repudiation at the
enforcement layer — confirmed), R-045 (named agent-threat controls — partial). 23 of 72 rows now carry
a result across V1–V6.

## J. Findings

| DEFECT | SEVERITY | PRE-EXISTING / INTRODUCED | ROOT CAUSE | IMPACT | FIX / DEFER | EVIDENCE |
|---|---|---|---|---|---|---|
| **F6-1** the detection plane does not cover gateway-enforced **external** agents | **Medium** | Pre-existing (structural) | all six rules key off ACT-run execution signals; `governance_denial_spike` joins `runtime_governance_decisions` to `agent_executions`, which external agents never produce. Their denials live in `external_gateway_calls` | sustained probing by an external agent raises **no** threat finding, so a security team gets no signal — even though every attempt is contained and attributed | DEFER → product change (extend the threat context to read the gateway plane) | `v6_detection_results.json` V6-D1: 12 denials → 0 findings |
| **F6-2** injection has no detection signal | Medium | Pre-existing, **documented by the product** | no deterministic content-denial taxonomy to key a rule off | injection is contained but never flagged as injection | DEFER → **O-1** | `rules.py` evidence-gap note; V6-D2 |
| carry-over | — | — | — | G-3 (MCP integrity/transport), I-1 (memory), I-2 (A2A edges), F-2 (V4 attribution scope), F5-1…F5-3 (V5), OB-1, OB-2 unchanged | DEFER | V3–V5 reports |

**No ACT product defect was found in the containment or enforcement path**, and no finding is a P0 or
a blocker.

## K. Product-change findings → O-1…O-11

- **New: extend detection coverage to the gateway plane (F6-1).** Feed `external_gateway_calls`
  denials into the threat context so a denial-spike rule can fire for gateway-enforced agents. This is
  the detection counterpart to the V4 F-2 attribution recommendation and is the most actionable output
  of this phase.
- **O-1** — prompt-injection detection signal (F6-2), unchanged from V3.
- Carry-over: **O-2/O-7** (memory + A2A observability), **O-3** (MCP description integrity),
  **O-4** (cross-agent correlation), **O-9** (identity correlation, from V5).

All recorded, none implemented.

## L. P0 / BLOCKER / STOP

**None triggered.** No false containment claim, no kill undone or bypassed or reactivated by
automation, no parallel enforcement path, no governance fail-open where mandatory, no over-claim via
mode confusion, no canary escape, no cross-tenant leakage, no T12 host-code execution.

## M. Artifacts

Lab tooling (lab-only): `lab/harness/v6_redteam.py`, `lab/wrapper/v6_run.py`. Docs: the nine
`docs/validation/v6/` deliverables. Evidence: the containment ground truth, four batch results,
measurements, pre-flight, the hash-chain `ledger.jsonl`, both boundary proofs, the ACT container log,
the batch log and the run log. No secrets: all values synthetic, the single synthetic sink token
redacted from the committed boundary proofs, no key material.
**`git diff 2dbc169 -- backend/ frontend/` is empty.**

## N. Git

Committed on `validation/v6-containment`; `main` untouched at `9667707`; not merged; pushed for review.

## O. V7 readiness

Reusable for V7: the wrapper with its per-batch boundary re-proof, the hash-anchored ledger, the
**effect-not-status** scoring discipline (V7 should score external-gateway enforcement the same way),
and the three-axis reporting split. Established and directly relevant: the 5.7 boundary held under
direct attack in V4, containment across that boundary is truthful and effect-verified here, and F6-1
names exactly where the gateway plane is not yet wired into detection — which V7's enforcement-mode
work should take as input. Still out of scope until their phases: T12 / framework RCE (needs the VM),
cloud (V8), and any ACT change. Prerequisites carried forward unchanged: re-prove the boundary before
each batch, hash-anchor evidence, keep canary escapes at zero.

**VERDICT: V6 CONDITIONAL — REVIEW REQUIRED**
