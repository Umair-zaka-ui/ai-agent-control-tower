# V0.2 — W-2 resolution and V0 closure record (2026-09-17)

Continues `README.md` (V0) and `closure-v0.1.md` (V0.1) in this directory. Authorized scope: the W-2
resolution under the reviewer's Option 1 ruling, the residue it created, the DB CHECK analysis (no
migration), regressions, evidence. The ruling and its rationale are recorded in
[ADR-0023](../../architecture/adr/0023-governed-requires-native.md).

Five separate historical records, none rewritten:

```
M5 CLOSE:                        2,639 passed / 1 failed / 1 deselected
V0 PRE-FIX BASELINE:             2,640 passed / 0 failed / 1 deselected   (frozen tree/DB; flake measured 3/50 separately)
V0 CONDITIONAL POST-FIXTURE RUN: 2,639 passed / 1 failed / 1 deselected   (W-7)
V0.1 CLOSURE RUN:                2,640 passed / 0 failed / 1 deselected
V0 FINAL CLEAN BASELINE (V0.2):  2,648 passed / 0 failed / 1 deselected   (this closure, frozen tree)
```

## A. Executive verdict

**VERDICT: V0 PASSED — READY FOR V1 AUTHORIZATION**

W-2 is closed under the reviewer's Option 1 ruling: `GOVERNED` ⇔ `NATIVE`, enforced once in `AgentControlStateService` (before the matrix, at every writer), with a stable `CONTROL_STATE_ORIGIN_INCOMPATIBLE` error, audited refusals, both `GOVERNED` edges removed from the matrix, mass assignment proven closed in both directions, and the M5.1 guard extended to the full matrix over the whole table. The M5.1 proof's step 6 now asserts the truthful terminal state *and* the refusal. All 103 non-native GOVERNED rows were fixture-attributable and removed; both producing fixtures corrected. Targeted: 348 passed, 2000 warnings in 446.20s (0:07:26); tenant: 113 passed, 2536 deselected, 1271 warnings in 316.38s (0:05:16). Full backend: 2,648 passed / 0 failed / 1 deselected. Frontend 384 passed, `tsc -b` clean, build green. ADR-0023 records the ruling. No migration; the DB CHECK is recommended for separate authorization.

## B. Starting branch / commit

`validation/v0-baseline` at `bbc159e` (the V0.1 closure), verified as the tip locally and on origin,
worktree clean; `main` = `origin/main` = `9667707`. W-7 and the deterministic guard were **not** redone.

## C. W-2 re-verification against live code

Unchanged from V0.1 §F, re-read this session: `AgentControlStateService` in
`backend/app/runtime/registry/control.py` is the only writer (`claim()`, `transition()`), called only from
`POST …/agents/{id}/claim` and `POST …/agents/{id}/control-state`; `CONTROL_TRANSITIONS` had
`REGISTERED → {GOVERNED, CLAIMED}` and `GOVERNED → {REGISTERED}` and `transition()` never read
`origin_category`. `control_state` / `origin_category` / `origin_provider` are absent from every write
schema; no raw SQL writes `agents`. Both defects were real: native demotion, and non-native "enrolment"
into GOVERNED.

## D. The final origin × control_state matrix (live enums)

`CONTROL_STATES = ("DISCOVERED", "CLAIMED", "REGISTERED", "GOVERNED")`,
`ORIGIN_CATEGORIES = ("NATIVE", "EXTERNAL", "UNKNOWN")`.

| origin \ control | DISCOVERED | CLAIMED | REGISTERED | GOVERNED |
|---|---|---|---|---|
| NATIVE | ✖ | ✖ (was reachable: W-2) | ✖ (was reachable: W-2) | ✔ only state |
| EXTERNAL | ✔ | ✔ | ✔ | ✖ (was reachable: `REGISTERED → GOVERNED`) |
| UNKNOWN | ✔ | ✔ | ✔ | ✖ (was reachable: `REGISTERED → GOVERNED`) |

Encoded once as `LEGAL_CONTROL_STATES_BY_ORIGIN` (`control.py`); the transition matrix is now
`DISCOVERED → {}` (left by `claim()`), `CLAIMED → {REGISTERED}`, `REGISTERED → {CLAIMED}`,
`GOVERNED → {}`. Lifecycle (`DRAFT` … `RETIRED`) stays orthogonal: a native agent is GOVERNED in every
lifecycle state. A GATEWAY_ENFORCED external agent is `EXTERNAL/REGISTERED`. An agent pending
reconciliation is `UNKNOWN/DISCOVERED`.

## E. Consistency confirmation

- **5.7's GATEWAY-stays-REGISTERED ruling** (ADR-0021): the matrix makes REGISTERED the terminal
  non-native state; the new rule is that ruling generalised, not a second opinion.
- **5.7's non-storable NATIVE_ENFORCED**: `effective_mode()` derives it from `control_state == GOVERNED`;
  GOVERNED is now itself unassertable by request, so NATIVE_ENFORCED cannot be reached by a write in any
  column. `test_v02_non_native_agent_cannot_reach_governed_by_request` asserts `effective_mode` stays
  `OBSERVED` after the refused request.
- **5.6's containment gate** reads the same column; with the matrix enforced it can neither perform a
  fake suspend (non-native GOVERNED) nor refuse a real one (native demoted).
- **M5.10's REFUSED-kill proof** (`test_ac02_ac03_ac04_the_milestone_5_end_to_end_proof`) ran unchanged
  and passed (§L, §M).

## F. Exact central implementation

| FILE | REASON | BEFORE | AFTER | TEST EVIDENCE |
|---|---|---|---|---|
| `backend/app/runtime/registry/control.py` | the invariant, in the one state machine | origin-agnostic matrix with `REGISTERED→GOVERNED` and `GOVERNED→REGISTERED`; rejections raised without audit | `LEGAL_CONTROL_STATES_BY_ORIGIN`, `is_origin_compatible()`, `_require_origin_compatible()` evaluated before the matrix in `claim()` and `transition()`; `GOVERNED` edges removed; `_reject()` records `RUNTIME_AGENT_CONTROL_STATE_REJECTED` (origin, current, target, code, reason) and commits before raising; docstrings updated | `test_v02_*`, `test_ac07_*`, `test_m51_end_to_end_proof` |
| `backend/app/identity/errors.py` | stable domain error | — | `CONTROL_STATE_ORIGIN_INCOMPATIBLE` → HTTP 409 | same |
| `backend/app/authorization/enums.py` | audit convention for refusals | — | `RUNTIME_AGENT_CONTROL_STATE_REJECTED` | `test_v02_native_demotion_is_rejected_and_audited` |

Authorization is unchanged: both routes still authorize through `require_permission` /
`AuthorizationGateway` (`runtime.agent.control.claim`, `runtime.agent.control.manage`); cross-tenant
remains 404 via `get_or_404`. No route logic, no frontend change, no second state machine.

## G. Mass-assignment closure

`test_v02_api_cannot_mass_assign_origin_or_control_state`: `POST /agents` with `origin_category`,
`origin_provider` and `control_state` in the body creates a `NATIVE / ACT_NATIVE / GOVERNED` row;
`PATCH /agents/{id}` with all three on an external agent returns 200 and changes none of them. The
fields remain absent from `AgentRegistrationCreate` / `AgentRegistryUpdate` (unknown fields ignored).

## H. `test_m51_end_to_end_proof` step 6

**Old assertion (verbatim):**
```python
    # 6. deliberate forward path: CLAIMED -> REGISTERED -> GOVERNED
    assert client.post(f"{RT}/agents/{ext_id}/control-state", headers=admin["headers"],
                       json={"target_state": "REGISTERED", "reason": "in scope"}).status_code == 200
    assert client.post(f"{RT}/agents/{ext_id}/control-state", headers=admin["headers"],
                       json={"target_state": "GOVERNED", "reason": "enrolled"}).status_code == 200
```
**New assertion (verbatim):**
```python
    assert client.post(f"{RT}/agents/{ext_id}/control-state", headers=admin["headers"],
                       json={"target_state": "REGISTERED", "reason": "in scope"}).status_code == 200
    r6 = client.post(f"{RT}/agents/{ext_id}/control-state", headers=admin["headers"],
                     json={"target_state": "GOVERNED", "reason": "enrolled"})
    assert r6.status_code == 409, r6.text
    assert r6.json()["error"]["code"] == "CONTROL_STATE_ORIGIN_INCOMPATIBLE"
    snap = client.get(f"{RT}/agents/{ext_id}/control-state", headers=admin["headers"]).json()
    assert snap["control_state"] == "REGISTERED"  # the refusal changed nothing
```
**Why the contract changed:** GOVERNED means ACT executes and enforces the agent; an external CrewAI
agent reaching it by request was an over-claim in the column 5.6 acts on (ADR-0023).
**Why coverage increased:** the step still exercises the forward path to REGISTERED (the truthful
terminal state), and additionally asserts the refusal, its stable code, and that the refusal left the
row untouched — three assertions where there was one 200.

The companion `test_ac07_govern_requires_an_owner` became
`test_ac07_govern_is_unreachable_for_a_non_native_agent_owner_or_not` (refused with the origin code
whether owned or not; row unchanged), and `test_ac07_transition_endpoint_enforces_the_matrix` now checks
a still-legal illegal edge (`DISCOVERED → REGISTERED` → `TRANSITION_INVALID`) **and**
`DISCOVERED → GOVERNED` → `ORIGIN_INCOMPATIBLE`.

## I. Residue provenance analysis + cleanup

Enumerated live before any change (`residue_enumeration` in this record's commit message log and
`residue_cleanup.log`): **103** non-native GOVERNED rows (the 99 reported had grown by V0.1's runs).

| Signal | 33 EXTERNAL rows | 70 UNKNOWN rows |
|---|---|---|
| organisation | "E2E Org", one agent each, users `m51_*` / `m51m_*@example.com` | "Posture Org", one agent each, users `posture_*@example.com` |
| shape | `External Agent <hex6>`, `agent_type='EXTERNAL'`, `api_key_hash=''`, owner USER, `created_by` set | `agent-<first 8 hex of own id>`, `api_key_hash='x'`, no owner, no `created_by` |
| linkage | only `RUNTIME_AGENT_REGISTERED` (the proof's own transitions); 0 audit_logs, 0 discovery rows | only `POSTURE_EVALUATED` / `POSTURE_FINDING_OPENED`; 0 discovery rows |
| timestamps | 2026-09-04 (M5.1 development) → 2026-09-17, one per full/targeted run | 2026-09-10 (5.5) → 2026-09-17; 52 created by V0's own 50-run loop |
| origin | `test_m51_end_to_end_proof` step 6 via the product seam + product transition path, on a test tenant | `tests/posture/test_security_posture.py:766` helper default (`control_state="GOVERNED"`) |
| negative control | rows outside either full signature: **0** | |

Classification: **103 / 103 `TEST RESIDUE (fixture-attributable)`; 0 PRODUCT-PATH ORIGIN; 0 UNKNOWN
PROVENANCE.** The EXTERNAL rows were produced *through* the product transition path, but by the proof
that asserted the wrong contract, in single-agent test tenants — no real reconciliation, claim or
operator did this. Cleanup deleted exactly the rows matching the two full signatures (script asserts the
signature count equals the invariant-violating count and that no row is unexplained); FK cascades
removed 164 `runtime_events` and 33 `agent_ownership_history` rows belonging to them. Post-cleanup:
0 violating rows; distribution EXTERNAL {CLAIMED 182, DISCOVERED 7,590, REGISTERED 140},
NATIVE {GOVERNED 117,649}, UNKNOWN {DISCOVERED 167}; 125,728 agents. Both producing fixtures corrected
(step 6; posture:766 now passes `control_state="DISCOVERED"`).

## J. DB CHECK analysis + recommendation (no migration)

With Option 1 the matrix is complete and stable for every legitimate state: retired/suspended native
agents stay `NATIVE/GOVERNED` (lifecycle orthogonal), UNKNOWN-pending-reconciliation is
`UNKNOWN/DISCOVERED` (reconciliation refines `origin_provider`, never control state), GATEWAY_ENFORCED
is `EXTERNAL/REGISTERED`. A CHECK `((origin_category = 'NATIVE') = (control_state = 'GOVERNED'))`
would reject **no** legitimate transition: every write path now either creates a compatible row
(model defaults, `record_external_agent`) or is refused by the service before reaching the database.
The live table satisfies it today (0 violations after cleanup). It is the strongest available guarantee
and the pattern that has worked here (M4.11a marker, 5.9 unstorable stale pass, 5.7 non-storable
NATIVE_ENFORCED). **Recommendation:** add it as `ck_agents_governed_iff_native` in a separately
authorized additive, reversible migration; the M5.1 guard's negative-control test must then plant rows
in a way the CHECK permits (or be changed to assert the CHECK fires). **Not created in V0.2.**

## K. Transition security tests (all in `tests/runtime/test_agent_asset_model.py`)

| Requirement | Test |
|---|---|
| valid NATIVE/GOVERNED preserved through lifecycle | `test_v02_native_agent_is_governed_in_every_lifecycle_state` |
| native demotion rejected + audited | `test_v02_native_demotion_is_rejected_and_audited` |
| non-NATIVE → GOVERNED rejected (EXTERNAL and UNKNOWN), legal progression and reverse allowed, escalation audited, 5.7 mode stays OBSERVED | `test_v02_non_native_agent_cannot_reach_governed_by_request[EXTERNAL|UNKNOWN]` |
| cross-tenant 404, no audit noise | `test_v02_cross_tenant_transition_is_404` |
| concurrent conflicting transitions, real separate sessions | `test_v02_concurrent_conflicting_transitions_preserve_the_invariant` |
| API cannot mass-assign | `test_v02_api_cannot_mass_assign_origin_or_control_state` |
| full-population guard bites in both directions | `test_v02_full_population_guard_bites_in_both_directions` |
| 5.7 / 5.10 proofs unchanged | `tests/bridge`, `tests/threat`, `tests/milestone` in §L and §M |

## L. Targeted regression

`v02_targeted_regression.log`, tree = all V0.2 changes on `bbc159e`:

| Invocation | Result |
|---|---|
| A: asset model (incl. the seven V0.2 tests), idempotency, posture, control graph, bridge, threat, milestone, registry/audit, discovery | **348 passed, 2000 warnings in 446.20s (0:07:26)** |
| B: `-k "tenant or cross_org or other_org or isolation or leak"` over the whole suite | **113 passed, 2536 deselected, 1271 warnings in 316.38s (0:05:16)** |

## M. Full backend regression

| COLLECTED | PASSED | FAILED | SKIPPED | DESELECTED | XFAILED | XPASSED | WARNINGS | DURATION |
|---|---|---|---|---|---|---|---|---|
| 2,649 | **2,648** | **0** | 0 | 1 | 0 | 0 | 16,732 | 1601.95 s (0:26:41) |

ONE run, isolated, frozen tree and tracking files, after §L. Start / end: 2026-09-17T23:14:18+05:00 → 2026-09-17T23:41:03+05:00. **No failure.**

## N. Frontend / TypeScript / build

`v02_frontend.log`: **52 files, 384 passed**; `tsc -b --noEmit` exit 0; `npm run build` exit 0 with the pre-existing >500 kB chunk warning. Backend-only closure.

## O. Tenant-isolation verification

§L invocation B (`-k "tenant or cross_org or other_org or isolation or leak"`): 113 passed, 2536 deselected, 1271 warnings in 316.38s (0:05:16). No leak.

## P. Truthful-control verification

`tests/threat`, `tests/bridge`, `tests/milestone` ran unchanged in §L-A and §M: the external kill stays
REFUSED, observed/claimed/registered containment truthfully refused, GOVERNED not downgradable to a
weaker claim, revocation immediate. With the matrix enforced, the state 5.6 reads can no longer be
declared.

## Q. Schema / migration status

No migration, no CHECK, no schema change. Head `0061_assurance_evidence` = live `alembic_version`.
The CHECK is recommended (§J) and awaits separate authorization.

## R. Files changed

| FILE | REASON | BEFORE | AFTER | TEST EVIDENCE |
|---|---|---|---|---|
| `backend/app/runtime/registry/control.py` | W-2 central invariant | see §F | see §F | §K, §L, §M |
| `backend/app/identity/errors.py` | stable error | — | `CONTROL_STATE_ORIGIN_INCOMPATIBLE` (409) | §K |
| `backend/app/authorization/enums.py` | rejection audit event | — | `RUNTIME_AGENT_CONTROL_STATE_REJECTED` | §K |
| `backend/tests/runtime/test_agent_asset_model.py` | step 6 correction, two AC-07 corrections, guard extended to the full matrix, seven V0.2 tests | see §H, §K | see §H, §K | §L, §M |
| `backend/tests/posture/test_security_posture.py:766` | fixture produced UNKNOWN+GOVERNED | helper default GOVERNED | `control_state="DISCOVERED"` | §I, §L |
| `docs/architecture/adr/0023-governed-requires-native.md` (+ README index row) | the ruling and its rationale | — | new | — |
| `docs/architecture/adr/0015-…`, `docs/runtime/registry/asset-model.md`, `docs/runtime/registry/api.md` | superseded statements corrected in place with pointers to ADR-0023 | "safe reverses", "enrol into GOVERNED", "reaches GOVERNED once 5.7 attaches a mode" | corrected | — |
| `docs/validation/v0/closure-v0.2.md` + `v02_*` logs | evidence | — | new | — |
| `REPO_STATE.md`, `ROADMAP.md`, `CHANGELOG.md` | tracking | V0.1 entries | + V0.2 entries; earlier records untouched | — |

No frontend source and no migration changed.

## S. Evidence artifacts (`docs/validation/v0/`)

`closure-v0.2.md` (this), `v02_residue_cleanup.log`, `v02_asset_model_run.log`,
`v02_targeted_regression.log`, `v02_full_regression_final.log`, `v02_frontend.log`, `v02_w2_changes.diff`.

## T. Remaining defects / debt

| DEFECT | SEVERITY | PRE-EXISTING / INTRODUCED | ROOT CAUSE | IMPACT | FIX / DEFER | EVIDENCE |
|---|---|---|---|---|---|---|
| W-2 (both directions) | Medium | Pre-existing (5.1) | origin-agnostic matrix; contradictory GOVERNED semantics | 0 native rows affected; 103 test rows removed | **FIXED** (ADR-0023) | §D–§K |
| W-9 posture:766 UNKNOWN+GOVERNED fixture default | Low | Pre-existing (5.5) | helper default | residue | **FIXED** | §I |
| DB CHECK for the matrix | — (hardening) | — | — | — | DEFER — recommended, needs migration authorization | §J |
| W-3, W-4, W-5, W-6, W-8 from V0 | Low | Pre-existing | — | — | DEFER (unchanged) | V0 §W |

## U. Documentation / tracking / ADR

ADR-0023 written and indexed; ADR-0015, `asset-model.md`, `api.md` corrected in place; REPO_STATE,
ROADMAP, CHANGELOG extended with V0.2 entries; RECOVERY unchanged (no schema change; the only DB change
is the deletion of 103 fixture-attributable rows and their cascaded test events). Historical records
stand as listed at the top. Repository search for test-count claims: the same stale README figures as
V0 §C (intentional historical references, left).

## V. Git status / commit / push

Committed on `validation/v0-baseline` on top of `bbc159e` as one closure commit; pushed to
`origin/validation/v0-baseline`; `main` untouched at `9667707`; not merged — awaiting architecture
review. Worktree clean after the commit.

## W. V1 readiness

Everything the gate asked for is in place: live truth, a corrected and residue-free baseline, a deterministic guard that bites, a deterministic idempotency test, the origin × control-state invariant enforced in the one state machine and asserted over the whole table, and a clean full run recorded exactly as produced. V1 is not begun; it awaits authorization.

**VERDICT: V0 PASSED — READY FOR V1 AUTHORIZATION**
