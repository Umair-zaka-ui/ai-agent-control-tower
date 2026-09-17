# ADR-0023 — `control_state = GOVERNED` requires `origin_category = NATIVE`; the origin × control-state matrix is enforced in the one control-state service and asserted over the whole table

- **Status:** Accepted
- **Date:** 2026-09-17
- **Deciders:** Post-Milestone-5 Validation Gate V0.2 (architecture review of the V0.1 §2A stop)
- **Supersedes:** — (corrects one anticipation in ADR-0015 and one M5.1 proof step; see "What this
  changes")
- **Relates to:** ADR-0015 (the asset model and `control_state` — this ADR fixes the meaning of its
  strongest value), ADR-0020 (truthful containment — reads the column this ADR protects), ADR-0021
  (truthful enforcement modes — this ADR is the same ruling, applied to the column 5.7 derives from).

## Context

`agents.control_state` answers "what relationship and *real enforcement authority* does ACT have over
this agent?" (ADR-0015). Its strongest value, `GOVERNED`, is read by two things that act on it:

- Phase 5.6's containment gate (`ContainmentOrchestrator.truthful_capability`) — containment is
  *performed* only when `control_state == 'GOVERNED'`; otherwise it is truthfully `REFUSED`.
- Phase 5.7's `effective_mode()` — `GOVERNED` **is** `NATIVE_ENFORCED`, the one mode ADR-0021 made
  unstorable so that full enforcement "has to be *true*, not declared".

Both therefore define `GOVERNED` as *ACT runs and enforces this agent*. ADR-0021 refused to promote a
GATEWAY_ENFORCED external agent to `GOVERNED` for exactly that reason: it "would have made 5.6's
`SUSPEND_AGENT` report success for an agent ACT cannot suspend".

But the repository contradicted itself. M5.1 shipped a generic transition matrix
(`CLAIMED → REGISTERED → GOVERNED` "and the safe reverses") that never consulted `origin_category`, and
its end-to-end proof asserted that an **external** CrewAI agent could be moved to `GOVERNED` by an
operator's request ("enrolled"). The Validation Gate's §9B trace (V0) found two consequences:

1. **W-2, the reported half:** a `control.manage` holder could move a **NATIVE** agent
   `GOVERNED → REGISTERED → CLAIMED`. 5.6 would then *refuse* to stop an agent ACT is actually running.
2. **The mirror half:** an **EXTERNAL / UNKNOWN** agent could be declared `GOVERNED` with no fact behind
   it. 5.6 would then report a successful suspend of an agent ACT does not run — precisely the
   false-containment failure Milestone 5.10's asserted-`REFUSED` kill exists to prove impossible, and a
   pilot blocker.

V0.1 stopped at the §2A condition because the `EXTERNAL/UNKNOWN × GOVERNED` cell could not be *derived*:
the documentation said an external agent reaches `GOVERNED` "only once Phase 5.7 attaches a NATIVE …
enforcement mode", 5.7 built no such operation, and no code path could ever establish that ACT runs an
agent whose provenance is that it exists outside ACT.

## Options considered

### Option 1 — `GOVERNED` is forbidden for any non-NATIVE origin (**chosen**)
- Pros: the only rule the repository's own definition of `GOVERNED` yields without adding semantics;
  identical to ADR-0021's reasoning; makes 5.6 and 5.7 read a column that cannot lie in either
  direction; complete for every legitimate state (below).
- Cons: one M5.1 proof step encoded the opposite and had to be corrected; 103 test-created rows
  (33 from that proof, 70 from a posture fixture default) had to be classified and removed.

### Option 2 — keep the request path but require an ACT-established precondition (e.g. an ACT runtime
definition plus an ACTIVE deployment ACT executes)
- Pros: would let an agent that *migrates into* ACT keep its external provenance.
- Cons: no such precondition exists in live code; `record_external_agent` creates rows that could never
  satisfy it; it is a new product semantic, i.e. designing the rule rather than deriving it.

### Option 3 — enforce only `NATIVE ⇒ GOVERNED` and leave external "enrolment" as M5.1 shipped it
- Pros: smallest diff, no test or data touched.
- Cons: leaves the over-claim direction open — the direction 5.6 acts on. A partially-correct invariant.

## Decision

We chose **Option 1**: `control_state = 'GOVERNED'` **if and only if** `origin_category = 'NATIVE'`.

**Rationale, recorded so it cannot silently return.** `GOVERNED` is not a label an operator assigns;
it is a consequence of a fact about the world — ACT executes the agent, therefore ACT holds full 4.3 /
kill-switch authority over it. That is the identical reasoning that made `NATIVE_ENFORCED` non-storable
in 5.7: full enforcement must be *true*, not *declared*. An external agent at `GOVERNED` is the same
over-claim in a different column — and it is the column 5.6 actually reads. Conversely a native agent
is `GOVERNED` in every lifecycle state, because ACT runs it whether it is `DRAFT`, `ACTIVE`, `SUSPENDED`
or `RETIRED`; lifecycle is an orthogonal axis (ADR-0015).

**The derived matrix** (live enum values; ✔ legal, ✖ illegal):

| `origin_category` \ `control_state` | DISCOVERED | CLAIMED | REGISTERED | GOVERNED |
|---|---|---|---|---|
| NATIVE | ✖ | ✖ | ✖ | ✔ |
| EXTERNAL | ✔ | ✔ | ✔ | ✖ |
| UNKNOWN | ✔ | ✔ | ✔ | ✖ |

Previously reachable cells that no longer are: `NATIVE × REGISTERED` and `NATIVE × CLAIMED` (via the
"safe reverse" `GOVERNED → REGISTERED`), and `EXTERNAL × GOVERNED` / `UNKNOWN × GOVERNED` (via
`REGISTERED → GOVERNED`).

**Completeness for every legitimate state.** A retired or suspended native agent: `NATIVE/GOVERNED`
(lifecycle only). An agent of undetermined provenance pending reconciliation: `UNKNOWN/DISCOVERED`
(5.2 creates it there; reconciliation may refine the provider, never the control state). A
GATEWAY_ENFORCED external agent: `EXTERNAL/REGISTERED`, exactly where ADR-0021 put it. No legitimate
state falls outside the matrix.

## Implementation

- **One authority.** `app/runtime/registry/control.py`: `LEGAL_CONTROL_STATES_BY_ORIGIN`,
  `is_origin_compatible()`, and `AgentControlStateService._require_origin_compatible()` evaluated at
  every writer (`claim()`, `transition()`) **before** the transition matrix — "would be an over-claim" is
  a more fundamental refusal than "no such edge". `record_external_agent` already refused `NATIVE`.
- **The matrix itself is now truthful:** `GOVERNED` has no edges in either direction
  (`REGISTERED → GOVERNED` and `GOVERNED → REGISTERED` removed). The owner precondition for `GOVERNED`
  is retained as defence in depth but is unreachable by construction.
- **Stable domain error:** `CONTROL_STATE_ORIGIN_INCOMPATIBLE` (HTTP 409), distinct from
  `CONTROL_STATE_TRANSITION_INVALID` so audits and clients can tell "wrong path" from "would be a lie".
- **Audit:** every refused move records `RUNTIME_AGENT_CONTROL_STATE_REJECTED` (origin, current state,
  target, code, reason) and **commits before raising**, the discipline of 5.6's
  `CONTAINMENT_ACTION_REFUSED`; successful moves keep `RUNTIME_AGENT_CONTROL_STATE_CHANGED`.
- **Mass assignment:** unchanged and now tested in both directions — `origin_category`,
  `origin_provider` and `control_state` are absent from every write schema and ignored on `POST`/`PATCH`.
- **The M5.1 guard** (`test_ac09`) asserts the full matrix over the **whole** table, built from the same
  `LEGAL_CONTROL_STATES_BY_ORIGIN` mapping the service enforces, so the two cannot drift; a companion
  test plants one violating row per direction and proves the guard fails.
- **No migration.** A DB CHECK (`(origin_category = 'NATIVE') = (control_state = 'GOVERNED')`) would
  now reject no legitimate state and is the stronger guarantee; it is recommended as a separately
  authorized follow-up, not created here.

## What this changes

- `test_m51_end_to_end_proof` step 6 previously asserted `200` on `target_state: "GOVERNED"` for an
  external agent; it now asserts `REGISTERED` as the truthful terminal state **and** that `GOVERNED` is
  refused with `CONTROL_STATE_ORIGIN_INCOMPATIBLE` — strictly more coverage. `test_ac07_govern_requires_an_owner`
  became `test_ac07_govern_is_unreachable_for_a_non_native_agent_owner_or_not`.
- ADR-0015's "`CLAIMED → REGISTERED → GOVERNED` and the safe reverses" and the asset-model document's
  "an external agent reaches this only once 5.7 attaches a NATIVE or GATEWAY enforcement mode" are
  corrected in place with a pointer here.

## Consequences

**Good.**
- The column 5.6 and 5.7 read cannot over-claim or under-claim by request; both phases keep one signal.
- ADR-0021's ruling is now the whole rule, not an exception to a generic matrix.
- A rejected security-relevant transition is an audited event, not a silent 4xx.

**Costs, accepted.**
- An agent that genuinely migrates into ACT's runtime cannot keep `EXTERNAL` provenance and become
  `GOVERNED`. If that product need ever arises it is a new native agent record with a provenance link,
  not a transition — which is also the truthful description of what happened.
- `ControlStateTransitionRequest` still syntactically accepts `GOVERNED` so the refusal is a domain
  error with a reason rather than a schema 422; a request that can never succeed remains expressible.
- 103 test rows had to be deleted and two test fixtures corrected; the shared dev database had been
  accumulating a state the product now forbids since 2026-09-04.
