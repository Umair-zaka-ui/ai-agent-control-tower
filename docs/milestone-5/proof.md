# Milestone 5 — the end-to-end proof

Phase 5.10. This document records what the Milestone 5 proof demonstrates, how
it demonstrates it, and what it deliberately refuses to claim.

The proof lives in
[`backend/tests/milestone/test_milestone_5_proof.py`](../../backend/tests/milestone/test_milestone_5_proof.py).

## Why the proof leaves the process

Milestone 5's thesis is **"govern the AI you didn't build."** A demonstration
assembled entirely from in-process service calls would establish that ACT's own
functions call each other correctly. That is not the claim, and proving it would
not close the milestone.

So the proof crosses the operating-system process boundary **twice, in both
directions**:

| Direction | What crosses | How |
|---|---|---|
| **Inbound** | ACT discovers an agent it did not build | A real `http.server` agent registry on a real socket; ACT fetches it over HTTP, holding no DB lock across the call |
| **Outbound** | The agent calls ACT | A **separate OS process** (`subprocess`) signs its own requests and calls ACT's gateway over a **real uvicorn socket** |

The external agent's source is parsed and asserted to import nothing from `app`
— it could not reach ACT's database or objects if it tried. That assertion is
what makes "external" mean something.

## The fourteen steps

Each step is a **real cause producing a real effect through a real authority**.
Nothing is pre-inserted to make a later step pass.

| # | Step | Real authority | Asserted effect |
|---|---|---|---|
| 1 | **Discovery** *(crosses inbound)* | `HttpAgentRegistryAdapter` | The registry server was actually contacted; one agent created |
| 2 | **Reconciliation** | `ReconciliationService` | A second sweep creates **0** and links 1 — exactly one canonical row |
| 3 | **Truthful landing** | 5.1 `control_state` | `DISCOVERED`, unowned — ACT knows it exists and has no authority |
| 4 | **Shadow** | `PostureEvaluator` | Shadow **with its conditions** — never a bare flag |
| 5 | **Blast radius** | 5.4 graph | The agent is shown reaching payroll via an **unapproved MCP** |
| 6 | **Claim** | `AgentControlStateService` | Guarded, audited, owner recorded |
| 7 | **Enforcement mode** | 5.7 | `GATEWAY_ENFORCED`; `reaches_agent_execution` is **false** |
| 8 | **Gateway call** *(crosses outbound)* | real socket + separate process | Allowed call dispatched to a real capability; forbidden call **denied** |
| 9 | **Threat detection** | `ThreatEvaluator` | Real runtime signal |
| 10 | **Truthful containment** | `ContainmentOrchestrator` | Kill **REFUSED** with a real reason; grant revocation is the real reach |
| 11 | **Authority chain** | 5.3 | Reconstructable |
| 12 | **Assurance** | 5.9 | Owner now **PASS**; traceability **INSUFFICIENT_EVIDENCE** |
| 13 | **Command center** | 5.8 | True estate state, truthful affordances |
| 14 | **Audit + isolation** | audit trail | Nine event types reconstruct the flow; tenant 2 gets 404 |

## What the proof refuses to assert

**It never asserts that ACT stopped the external agent** — because ACT cannot.
The agent runs outside ACT; Phase 5.6 refuses to fake a kill it cannot perform.

So step 10 asserts the *truthful* outcome:

```
SUSPEND_AGENT  →  status = REFUSED
                  refusal_reason names the missing authority
                  authority_ref is empty (a refusal names no authority row)
```

…and then asserts that the containment ACT **genuinely holds** at this reach —
revoking the boundary grant — takes effect, verified by re-running the external
process and watching the call be refused with nothing reaching the capability.

An earlier draft of this proof asserted a *successful* `SUSPEND_AGENT`. That
draft would have passed only if the platform lied. Rewriting the assertion to
match what ACT can truthfully do is the single most important line in the file.

## The §44 gate audit (A–R)

All eighteen gates map to a named passing proof. The four this phase owns
directly:

| Gate | Concern | Proof |
|---|---|---|
| **N** | Tenant isolation, adversarial **and per-hop** | `test_ac06_*` |
| **O** | Scale measured, no full scan, no graph DB | `test_ac09` |
| **Q** | M1–M4 + 5.1–5.9 regression unchanged | the full suite + `test_ac14` |
| **R** | The E2E crossing the process boundary | `test_ac02_ac03_ac04` |

The remaining fourteen are closed by their owning phase's tests, composed here
rather than duplicated. The SRS §44 consolidated table is not carried in the
repository, so the letter↔concern mapping is reconstructed from the per-phase
gate references — the same gap Phase 4.10 reported for §41, recorded here rather
than silently assumed.

## Scale

The blast-radius traversal is timed over a single busy tenant (the Phase 5.4
fixture shape, elevated): 4,000 real agent rows, 400 tools, 100 payroll-kind
resources, 4,400 edges, `ANALYZE`d before timing.

**Measured: `agents-reaching` in 98.9 ms and 119.9 ms across two runs.**

The assertion is a **generous ceiling** (5 s) — it exists to detect a cliff, not
to police a micro-benchmark, because a tight bound on shared developer hardware
would be a flake generator rather than a guarantee.

One fixture lesson worth recording: a first draft inserted edges from phantom
agent UUIDs and the traversal returned nothing. That was the graph **working** —
every hop resolves its node against the tenant's real rows, which is precisely
what stops a foreign or fabricated id extending a chain (Gate N). The fixture
was corrected to insert real rows; the guard was not touched.

**The restraint outcome stands:** the relational recursive CTE meets the target,
so **no projection and no graph database** were introduced (ADR-0017). The proof
additionally asserts that no graph-database dependency has appeared in
`requirements.txt`.

## Failure semantics, proven together

The two planes meet in one test:

- **Discovery fails open** — a source outage degrades to staleness. The
  previously discovered agent is **still there**; absence of evidence is never
  evidence of absence, and an outage must never delete estate.
- **Assurance fails to INSUFFICIENT_EVIDENCE** — asked about evidence it does
  not have, it refuses to fabricate a pass.
- **Containment fails closed and loud** — a mandatory containment that cannot
  complete is `REFUSED` with a reason, never a silent pass.

## Defects found

The governing rule: **a proof that cannot pass reveals a real gap — fix the gap
and report it; never weaken the proof.** One real defect was surfaced.

### 5.2 — the loser of two concurrent sweeps escaped as an unhandled error

**Surfaced by:** `test_ac08_concurrent_discovery_sweeps_create_exactly_one_agent`.

**What happened.** Two sweeps of the same source overlapped (a manual trigger
during a scheduled one is the real-world shape). Both loaded the same agent row
at `row_version = N`; the first committed `N → N+1`; the loser's `UPDATE …
WHERE row_version = N` matched zero rows and SQLAlchemy raised
`StaleDataError`. That is the optimistic lock doing exactly its job — and it is
why **no duplicate was ever created**. The invariant held throughout.

**The gap.** `app/models/agent.py` states that this exception is "caught at the
service layer and translated to `AGENT_CONCURRENT_MODIFICATION`". The registry
service honours that contract. `DiscoveryRunService.run_source` did not, so the
losing sweep surfaced as an unhandled 500 and left its run row dangling at
`STARTED`.

**The fix** (`app/discovery/service.py`). The reconcile-through-commit block
now catches `StaleDataError`, rolls back, and finishes the run as a truthful
`FAILED` record whose reason names `AGENT_CONCURRENT_MODIFICATION` and states
that the observations were persisted, nothing was duplicated, and the other
sweep's result stands. It follows this service's own convention for every other
failure (fetch failures finish the run the same way) rather than raising —
because discovery is the **fail-open plane**: a sweep must never surface a 5xx
to the scheduler that drove it, and the run row is the durable, audited record.
One subtlety: `observations_count` is assigned after the observations' own
commit, so it is re-set after the rollback — otherwise the FAILED run would
under-report what it genuinely persisted.

**Proven.** The overlap cannot be forced deterministically without instrumenting
product code, so `test_ac13_the_5_2_concurrent_sweep_gap_is_fixed_and_proven`
proves the *handler*: the real exception type is raised from the reconciliation
collaborator, and the run must finish `FAILED`, never dangle, never escape, and
never under-report. The race proof additionally asserts that no concurrent
outcome is a raised error — so it will catch any regression whenever the race
genuinely overlaps. The full 5.2 suite passes unchanged with the fix in place.

**Not weakened.** The race proof's invariant assertion (exactly one canonical
row) is untouched. The proof was made to *observe* the loser's outcome rather
than crash on it, and then to assert what that outcome must be.
