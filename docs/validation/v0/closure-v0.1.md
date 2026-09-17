# V0.1 — Conditional closure record (2026-09-17)

Continues the V0 bundle in this directory. Authorized scope: W-7 fix, W-2 fix, deterministic 5.1 guard,
regressions, evidence. **W-2 hit the §2A stop-condition and was not implemented** (see §F–§I). No product
code, no migration, no schema change. Branch `validation/v0-baseline`, starting commit `ad06bcf`
(verified: branch tip, worktree clean, `main` and `origin/main` at `9667707`, branch not on origin).

Four separate historical records, none rewritten:

```
M5 CLOSE:                          2,639 passed / 1 failed / 1 deselected
V0 PRE-FIX BASELINE:               2,640 passed / 0 failed / 1 deselected   (frozen tree/DB; flake measured 3/50 separately)
V0 CONDITIONAL POST-FIXTURE RUN:   2,639 passed / 1 failed / 1 deselected   (W-7)
V0.1 FINAL CLEAN BASELINE:         2,640 passed / 0 failed / 1 deselected   (this closure, frozen tree)
```

## A. Executive verdict

**VERDICT: V0 CONDITIONAL — REVIEW REQUIRED** — the suite is clean, but W-2 stopped at the §2A condition and awaits the reviewer's decision (§G).

W-7 fixed and proven (constant score 0.2548; 30/30; still fails under broken scoping). The 5.1 guard is now a full-population invariant query (~71 ms, proven to bite). W-2 was re-verified and the origin × control-state matrix derived from live code; the EXTERNAL/UNKNOWN × GOVERNED cell cannot be derived — the repository both defines GOVERNED as "ACT runs and enforces this agent" and ships an M5.1 proof that grants it to an external agent by request — so per §2A nothing was implemented and three options are put to the reviewer. Full backend: 2,640 passed / 0 failed / 1 deselected.

## B. Starting branch / commit

`validation/v0-baseline` at `ad06bcf`, verified as the branch tip with a clean worktree; `main` = `origin/main` = `9667707`; the branch was not on origin. No STOP condition.

## C. W-7 re-verification (live code)

`AgentDuplicateDetectionService.check` (`app/runtime/registry/duplicates.py:42-70`) scores a registering
agent against **every** other agent in its organization: `0.5·name + 0.25·description + 0.25·business_purpose`
with `difflib.SequenceMatcher(...).ratio()` on lower-cased, stripped strings (`_ratio`, line 31-34);
`≥ 0.85` → `LIKELY_DUPLICATE`, `≥ 0.72` → `POSSIBLE_DUPLICATE`. `register()` (`services.py:105-113`) refuses
with `AGENT_DUPLICATE_REVIEW_REQUIRED` (409) while an unreviewed LIKELY match exists. The helper
`_register_agent` (`tests/authorization/test_runtime.py:46-49`) named agents `Agent <6 hex>` with the same
description and purpose for every agent; exactly one test registers two agents in one org. Diagnosis
confirmed unchanged from V0. **The production algorithm and thresholds were not touched.**

## D. Exact W-7 fix

| | |
|---|---|
| FILE | `backend/tests/authorization/test_runtime.py` |
| REASON | make the two same-org agents *deterministically* distinct under the live scoring model |
| BEFORE | `_register_agent(..., criticality)` hard-coded `name=f"Agent {uuid.uuid4().hex[:6]}"`, `description="A test agent."`, `business_purpose="Exercise the runtime in tests."`; `_ready_agent` forwarded only `criticality`; the test called `_ready_agent(client, org)` twice |
| AFTER | `_register_agent` gains optional `name`, `description`, `business_purpose` (defaults identical to before, so the other 32 call sites are unchanged); `_ready_agent` forwards `**agent_fields`; the test passes fixed fields: A = "Ledger reconciliation agent" / "Reconciles nightly ledger batches." / "Prove idempotency keys are scoped to one agent."; B = "Payroll notifier" / "Sends payroll run notices to staff." / "Show a shared key never crosses to another agent." — plus a comment stating the arithmetic |
| Previous score | identical description and purpose contribute `0.25 + 0.25 = 0.5`, so weighted = `0.5·name_ratio + 0.5`; any name ratio ≥ 0.70 blocks. The V0 failing pair `Agent cfbd5b` / `Agent c8fd67`: name ratio 0.75 → **0.875 ≥ 0.85** (blocked). Monte-Carlo over 200,000 random pairs: 5.40% blocked |
| New score | name 0.1395, description 0.2609, purpose 0.4792 → weighted **0.2548** — below the 0.72 POSSIBLE floor, no match row recorded at all, and the same value on every run (no randomness left in the pair) |
| Still tests scoping | the assertion is unchanged: same `idempotency_key` sent to agent A then agent B must yield two `201`s with different execution ids. `IdempotencyService.check` (`services.py:2443-2447`) scopes the lookup by `organization_id AND agent_id AND key`. Negative control (`w7_negative_control_test.py`, scratch): with `check` monkeypatched to an org-scoped lookup that ignores `agent_id`, the corrected test **raises AssertionError**; with the real service it passes — so the test still fails if per-agent scoping were broken |
| TEST EVIDENCE | §E, §L, §M |

## E. W-7 repeatability proof

`negative_controls_and_w7_repeat.log`: the corrected test, 30 consecutive fresh `pytest` processes,
**30 passed / 0 failed** (25–26 s each); then the whole `tests/authorization/test_runtime.py` once:
**49 passed**. Bounded loop, every run recorded, no retry-until-green. With the pair now scoring a
constant 0.2548 the failure mode is not merely improbable — it is not reachable.

## F. W-2 re-verification (from live code, this session)

- **Single authoritative state machine:** `AgentControlStateService` in `backend/app/runtime/registry/control.py`
  (`claim()` lines 208-269, `transition()` 271-333). Its only callers are the two routes
  `POST /api/v1/runtime/agents/{id}/claim` (`routes.py:473-491`, permission `runtime.agent.control.claim`)
  and `POST …/{id}/control-state` (`routes.py:495-501`, permission `runtime.agent.control.manage`),
  plus the M5.1 tests. No other module, service, worker or migration writes `control_state`
  (`grep` over `app/`: assignments only at `control.py:146, 236, 307`; no raw `UPDATE agents`).
- **Live enums:** `CONTROL_STATES = ("DISCOVERED","CLAIMED","REGISTERED","GOVERNED")`,
  `ORIGIN_CATEGORIES = ("NATIVE","EXTERNAL","UNKNOWN")` (`control.py:53,56`), both CHECK-constrained
  (`0054`). `origin_provider` is a soft string. `ControlStateTransitionRequest.target_state` pattern
  `^(CLAIMED|REGISTERED|GOVERNED)$` (`schemas.py:244`); `control_state`/`origin_category` are read-only
  in every schema (mass-assignment proven ignored by `test_m51_end_to_end_proof` step 5).
- **The matrix as coded** (`CONTROL_TRANSITIONS`, `control.py:77-82`):
  DISCOVERED→{} (left only by `claim()`), CLAIMED→{REGISTERED}, REGISTERED→{GOVERNED, CLAIMED},
  GOVERNED→{REGISTERED}. `transition()` checks: target is a state; matrix allows; GOVERNED needs an
  owner. **It never reads `origin_category`.** Lifecycle status is an orthogonal axis the module
  "never reads or writes" (module docstring).
- **W-2 confirmed:** a `control.manage` holder can POST `target_state=REGISTERED` on a NATIVE agent
  (GOVERNED→REGISTERED is in the matrix), then `CLAIMED`. Nothing in the service, route, gateway or
  schema prevents it. Not executed against the DB (it would plant the very residue V0 cleaned); the
  code path is unconditional and the negative-control harness for the guard shows what such a row does.
- **Audit convention for rejections:** `_record_event` is used for successful claims/transitions
  (`RUNTIME_AGENT_CLAIMED`, `RUNTIME_AGENT_CONTROL_STATE_CHANGED`); refusals elsewhere use a dedicated
  event (`CONTAINMENT_ACTION_REFUSED`, `RUNTIME_DEPLOYMENT_REJECTED`, `AUTHORIZATION_DENIED`). No
  `RUNTIME_AGENT_CONTROL_STATE_REJECTED` event exists yet; the M5.1 service raises before recording.
- **Error convention:** `CONTROL_STATE_TRANSITION_INVALID` (409) for an illegal move,
  `CONTROL_STATE_TRANSITION_FORBIDDEN` (403) for a move the state machine allows but a precondition
  forbids (`errors.py:449-450, 917-918`).

## G. The origin × control-state rule — derived, not designed

What the repository *says* GOVERNED means, in order of authority:

| Source | Statement |
|---|---|
| `app/models/agent.py:172-185` (5.1 comment, corrected by 5.7) | "GOVERNED — ACT has real enforcement authority: it runs and enforces this agent (every native agent)… Native rows are GOVERNED and may be in any lifecycle_status." |
| `app/bridge/modes.py` / ADR-0021 | "`GOVERNED` means *ACT runs and enforces this agent*"; NATIVE_ENFORCED is derived from it and not storable; a GATEWAY_ENFORCED external agent **stays at REGISTERED** because promoting it "would have made 5.6's SUSPEND_AGENT report success for an agent ACT cannot suspend". |
| `app/threat/containment.py:67,135` | containment authority exists iff `control_state == 'GOVERNED'`. |
| ADR-0015 §"Revisit when" | "`GOVERNED` keeps its single meaning, 'ACT runs and enforces this agent'". |
| `docs/runtime/registry/asset-model.md:47-50` | "GOVERNED — ACT has real enforcement authority. Every native agent; **an external agent reaches this only once Phase 5.7 attaches a `NATIVE` or `GATEWAY` enforcement mode.**" |
| `app/bridge/service.py:71-77` | to obtain NATIVE_ENFORCED: "Bring the agent under ACT's control through the agent control-state workflow instead." |
| `tests/runtime/test_agent_asset_model.py::test_m51_end_to_end_proof` step 6 | an EXTERNAL (CREWAI) agent is moved CLAIMED→REGISTERED→**GOVERNED** ("enrolled") and the test asserts 200. |

**Derived matrix** (rows = `origin_category`, columns = `control_state`; ✔ legal, ✖ illegal, **?** unresolved):

| | DISCOVERED | CLAIMED | REGISTERED | GOVERNED |
|---|---|---|---|---|
| **NATIVE** | ✖ (only writer of DISCOVERED rejects NATIVE) | ✖ (reachable only via W-2) | ✖ (reachable only via W-2 — **the cell W-2 allowed**) | ✔ **the only legal state**: "every native agent", server default, 0054 backfill, 5.1 guard, no caller or test ever demotes one |
| **EXTERNAL** | ✔ (5.2 creates it here) | ✔ (`claim()`) | ✔ (generic transition; where a GATEWAY_ENFORCED agent lives per ADR-0021) | **?** — see below |
| **UNKNOWN** | ✔ (5.2 / `record_external_agent`) | ✔ | ✔ | **?** — same question as EXTERNAL |

Lifecycle status (`retired`, `suspended`, `DRAFT` …) is orthogonal by design: a NATIVE agent that is
retired or suspended is still `GOVERNED` (the model comment says "any lifecycle_status" and the module
never reads lifecycle). The 5.7 GATEWAY_ENFORCED case is *consistent* with this matrix: it lives at
REGISTERED and the matrix does not touch it. The rule "NATIVE ⇒ GOVERNED, immutable" is **fully derived**
for the NATIVE row and touches no other cell.

**The unresolved cell — EXTERNAL/UNKNOWN × GOVERNED.** Every authority above agrees GOVERNED means
"ACT runs and enforces this agent", and 5.7 made that claim non-assertable *for the mode column*. But
the same repository (a) documents that an external agent reaches GOVERNED "only once 5.7 attaches a
NATIVE … enforcement mode" — a path 5.7 then did not build (there is no "attach native enforcement"
operation; `agent_type='EXTERNAL'` rows have no runtime definition, version or deployment), (b) has
5.7 itself pointing operators at the generic control-state workflow to obtain NATIVE_ENFORCED, and
(c) keeps an M5.1 proof that asserts an EXTERNAL CrewAI agent *can* be moved to GOVERNED by an
operator's request alone. So today the generic transition lets an operator **declare** that ACT runs
an agent it does not run — exactly the "stronger enforcement state without real authority" the prompt's
opposite-direction requirement names, and the same over-claim ADR-0021 refused for GATEWAY_ENFORCED.
Nothing in live code defines what "real enrollment/enforcement authority" for an external agent would
consist of, so the rule for that cell cannot be *derived* — it must be *decided*. Per §2A this is a
STOP: implementing only the NATIVE half would leave the opposite direction open, and inventing a
precondition for the EXTERNAL cell would be designing the rule the prompt forbids.

**Options for the reviewer (with blast radius measured this session):**

1. **Forbid GOVERNED for any non-NATIVE origin** (GOVERNED becomes exactly "native, ACT-run").
   Rule: `origin_category != 'NATIVE' ⇒ control_state ∈ {DISCOVERED, CLAIMED, REGISTERED}`;
   NATIVE ⇒ GOVERNED. Complete, and the most consistent with ADR-0021/5.6. Blast radius:
   `test_m51_end_to_end_proof` step 6 (asserts 200 on GOVERNED for an external agent) must be rewritten
   intent-preservingly (assert the truthful refusal); `test_ac07_govern_requires_an_owner` keeps
   passing only if the owner check still fires first or its expected code is updated; the DB holds
   **31 EXTERNAL/GOVERNED + 68 UNKNOWN/GOVERNED** rows: the EXTERNAL ones come from that proof's step 6;
   the UNKNOWN ones from `tests/posture/test_security_posture.py:761` (`_insert_agent(..., origin_category=
   "UNKNOWN")` on the helper's `control_state="GOVERNED"` default — a second fixture inconsistency of the
   V0 kind, legal today, illegal under option 1). Both would need the V0 §I residue treatment and a
   one-argument fixture correction before a deterministic guard could assert the cell.
   `bridge/service.py:71-77` wording must change (there would be no workflow to NATIVE_ENFORCED for an
   external agent). Docs `asset-model.md:47-50` and ADR-0015 need the sentence corrected.
2. **Keep the M5.1 path but require an ACT-established precondition** (e.g. the agent has an ACT
   runtime definition + an ACTIVE deployment ACT executes). Truthful in principle, but **no such
   precondition exists in live code** and `record_external_agent` creates rows that can never satisfy
   it — this would be new product semantics, i.e. designing the rule.
3. **Enforce only NATIVE ⇒ GOVERNED (immutable) now; leave EXTERNAL→GOVERNED as M5.1 shipped it.**
   Closes the demotion hole, changes no test, no data. Leaves the declared-GOVERNED over-claim for
   external agents open and documented — which the prompt explicitly calls a partially-correct
   invariant and forbids without review.

**Recommendation:** option 1. It is the only rule the repository's own definition of GOVERNED yields
without adding semantics, and it is what ADR-0021 already decided for the GATEWAY half. It requires
touching one M5.1 proof step intent-preservingly and cleaning test residue, both of which need the
reviewer's explicit authorization (the V0.1 prompt forbids altering M5 proofs and creating a second
correction without it).

## H. Exact W-2 fix — **NOT APPLIED** (§2A stop-condition)

Nothing in `app/` was changed. The minimum central validation, once the cell is decided, is a single
origin-aware check inside `AgentControlStateService.transition()` (and `claim()`, which already
rejects non-DISCOVERED rows) before the matrix lookup, raising `CONTROL_STATE_TRANSITION_FORBIDDEN`
with a reason that names the rule, and recording a rejection audit event
(`RUNTIME_AGENT_CONTROL_STATE_REJECTED`, following `CONTAINMENT_ACTION_REFUSED`'s convention) —
no second state machine, no route-level logic, no schema change, no migration.

## I. Transition security tests — **designed, not written** (they encode the undecided rule)

- native GOVERNED preserved through unrelated lifecycle moves (`_register_native` + activate/retire);
- `POST …/control-state {target_state: REGISTERED}` on a NATIVE agent → 403
  `CONTROL_STATE_TRANSITION_FORBIDDEN`, row unchanged, rejection audited;
- external DISCOVERED→claim→REGISTERED still 200; REGISTERED→GOVERNED per the decided rule;
- cross-tenant transition → 404 (existing `get_or_404` convention);
- two real `SessionLocal()` sessions racing a native demotion and an external promotion: invariant holds
  in both outcomes (pattern of `test_ac10_concurrent_claims_exactly_one_wins`);
- PATCH `/agents/{id}` with `origin_category`/`control_state` in the body → ignored (extends step 5 of the
  M5.1 proof to `origin_category`);
- 5.10/5.6/5.7 truthful-containment proofs re-run unchanged (they were, in §L/§P of this closure: green).

## J. Deterministic invariant-guard change

| | |
|---|---|
| FILE | `backend/tests/runtime/test_agent_asset_model.py` — `test_ac09_existing_agents_are_backfilled_native_and_governed` |
| BEFORE | `db.query(Agent).limit(500).all()` (no ORDER BY) then per-row asserts: enum membership; `NATIVE ⇒ control_state == GOVERNED and origin_provider == ACT_NATIVE` |
| AFTER | one `SELECT count(*) FROM agents WHERE <violates>` with `<violates> = control_state NOT IN CONTROL_STATES OR origin_category NOT IN ORIGIN_CATEGORIES OR (origin_category='NATIVE' AND (control_state<>'GOVERNED' OR origin_provider<>'ACT_NATIVE'))`, built with the live `CONTROL_STATES` / `ORIGIN_CATEGORIES` tuples from `app.runtime.registry.control` and SQLAlchemy `or_/and_/not_in`; asserts the count is 0 and, on failure, names the ten oldest violating rows (id, name, origin, provider, state). The "population is non-empty" precondition is kept as a full `count(*) > 0`. |
| Semantics | strictly stronger, never weaker: the same three predicates, applied to **every** row instead of an arbitrary 500; the enum predicates are kept even though the DB CHECKs already enforce them, so nothing the old test asserted was dropped. No sampling, no LIMIT on the assertion. |
| Negative control | `guard_negative_control.py` (scratch, not committed): planted one NATIVE+DISCOVERED row → guard **failed** naming it (`rc=1`); deleted it → guard **passed** (`rc=0`); violations after: 0 |
| No migration, no DB CHECK | per §3/§7 of the closure prompt; the §2A stop on W-2 also means the EXTERNAL/UNKNOWN × GOVERNED cell is deliberately **not** asserted by this guard |

## K. Guard performance / query evidence

`EXPLAIN (ANALYZE, BUFFERS)` of the violating-rows query on the live table (116,165 rows at the time):

```
Seq Scan on agents  (cost=0.00..12151.26 rows=14102 width=43) (actual time=71.236..71.236 rows=0 loops=1)
  Filter: (control_state <> ALL(...) OR origin_category <> ALL(...) OR (origin_category='NATIVE' AND (control_state<>'GOVERNED' OR origin_provider<>'ACT_NATIVE')))
  Rows Removed by Filter: 116165
  Buffers: shared hit=42 read=9062
Planning Time: 0.255 ms
Execution Time: 71.248 ms
```

One sequential scan, ~71 ms cold (9,062 buffers read from disk), returning zero rows; the old sampled
query cost about the same per run (it loaded 500 full ORM rows) while checking 0.4% of the table. The
guard's own wall time is dominated by app import and the `client` fixture (~20 s per isolated run,
unchanged). At 10× the current population the scan would still be well under a second.

## L. Targeted regression (§4)

`targeted_regression.log`, tree = the two test-file edits, commit `ad06bcf`:

| Invocation | Result |
|---|---|
| A: `tests/authorization/test_runtime.py` (idempotency), `tests/runtime/test_agent_asset_model.py` (M5.1 asset/control-state incl. the new guard, claims, races), `tests/posture` (M5.5), `tests/graph/test_control_graph.py` (ownership/authority chains), `tests/bridge` (M5.7), `tests/milestone` (M5.10 truthful-control E2E), `tests/authorization/test_agent_registry.py` + `tests/identity/auth/test_security_event_audit.py` (authorization/audit) | **268 passed, 0 failed**, 4:42 |
| B: `-k "tenant or cross_org or other_org or isolation or leak"` over the whole suite | **112 passed, 0 failed**, 2,529 deselected, 5:28 |
| Earlier in the chain: corrected idempotency test ×30 and its file once | 30/30, 49 passed (§E) |

## M. Full backend regression (§5)

`full_regression_final.log` — ONE run, isolated, frozen tree and tracking files, started only after §L:

| COLLECTED | PASSED | FAILED | SKIPPED | DESELECTED | XFAILED | XPASSED | WARNINGS | DURATION |
|---|---|---|---|---|---|---|---|---|
| 2,641 | **2,640** | **0** | 0 | 1 | 0 | 0 | 16,685 | 1478.14 s (0:24:38) |

Start / end: 2026-09-17T18:47:43+05:00 → 2026-09-17T19:12:24+05:00. **No failure.**

## N. Frontend / TypeScript / build (§6)

`frontend.log`: **52 files, 384 passed, 0 failed** (50.7 s); `tsc -b --noEmit` exit 0; `npm run build` exit 0,
`✓ built in 2.49s`, with the pre-existing >500 kB chunk warning. Backend-only closure; nothing changed.

## O. Tenant-isolation verification

§L invocation B: 112 passed, 0 failed, across canonical agents, discovery, claims, control graph, findings,
bridge, assurance, milestone per-hop proofs and the M4 existence-leak proof. No leak.

## P. Truthful-control verification

`tests/threat`, `tests/bridge`, `tests/milestone` ran unchanged in §L-A (bridge, milestone) and in the full
run (§M): the external kill stays REFUSED (`test_ac02_ac03_ac04_the_milestone_5_end_to_end_proof`),
observed/claimed/registered containment truthfully refused, GOVERNED cannot be downgraded to a weaker
claim, revocation immediate. No proof was altered.

## Q. Schema / migration status

No migration, no DB CHECK, no schema change. Head `0061_assurance_evidence` = live `alembic_version`.
The DB CHECK for the origin/control invariant stays deferred behind the W-2 decision (§G): adding it
today would encode the undecided cell.

## R. Files changed

| FILE | REASON | BEFORE | AFTER | TEST EVIDENCE |
|---|---|---|---|---|
| `backend/tests/authorization/test_runtime.py` | W-7 | helper hard-codes `Agent <6 hex>` + identical description/purpose; test uses defaults | helper takes optional `name`/`description`/`business_purpose` (defaults unchanged); `_ready_agent` forwards them; the one two-agent test passes fixed, unrelated fields (score 0.2548) | §D, §E, §L, §M |
| `backend/tests/runtime/test_agent_asset_model.py` | deterministic 5.1 guard | `limit(500)` sample, per-row asserts | full-population violating-rows count asserted 0, oldest violators named on failure | §J, §K, §L, §M |
| `docs/validation/v0/*` | evidence | V0 bundle | + this closure record and its logs | — |
| `REPO_STATE.md`, `ROADMAP.md`, `CHANGELOG.md` | tracking | V0 CONDITIONAL entries | + V0.1 closure entries; earlier records untouched | — |

No file under `backend/app/`, `backend/migrations/` or `frontend/src/` changed.

## S. Evidence artifacts (`docs/validation/v0/`)

`closure-v0.1.md` (this), `v01_negative_controls_and_w7_repeat.log`, `v01_targeted_regression.log`,
`v01_full_regression_final.log`, `v01_frontend.log`, `v01_w7_and_guard.diff`, `v01_w7_negative_control_test.py`,
`v01_guard_negative_control.py` (both scratch harnesses, kept as evidence, not collected by pytest).

## T. Remaining defects / debt

| DEFECT | SEVERITY | PRE-EXISTING / INTRODUCED | ROOT CAUSE | IMPACT | FIX / DEFER | EVIDENCE |
|---|---|---|---|---|---|---|
| **W-2** native demotion via generic transition; and the mirror over-claim, an operator-declared GOVERNED for an EXTERNAL/UNKNOWN agent | Medium (truthful-control-state integrity) | Pre-existing (5.1) | `transition()` is origin-agnostic; the repository defines GOVERNED as "ACT runs it" but keeps an M5.1 path that grants it by request | 0 native rows affected; 31 EXTERNAL + 68 UNKNOWN GOVERNED rows exist (all test-created) | **DEFERRED — §2A STOP; decision requested (§G options)** | `w2_analysis` §F–§I |
| W-9 `tests/posture/test_security_posture.py:761` creates UNKNOWN + GOVERNED (helper default) | Low today; becomes a violation under W-2 option 1 | Pre-existing (5.5) | same helper-default pattern as W-1 | test residue of a kind the guard does not (yet) assert | DEFER with W-2 | §G |
| W-3, W-4, W-5, W-6, W-8 from V0 | Low | Pre-existing | — | — | DEFER (unchanged) | V0 §W |

## U. Documentation / tracking updates

`docs/validation/v0/closure-v0.1.md` + logs added; REPO_STATE (V0 delta extended with a V0.1 paragraph),
ROADMAP (V0 paragraph extended), CHANGELOG (V0 entry extended). RECOVERY unchanged (no DB or schema
change beyond one planted-and-deleted negative-control row). The four historical records stand as listed
at the top. Repository search for test-count claims: the same stale README figures as V0 §C (intentional
historical references, left).

## V. Git status / commit / push

Committed on `validation/v0-baseline` on top of `ad06bcf` as one closure commit (its hash is in `git log`;
a document cannot carry its own commit hash). `main` untouched at `9667707`. The branch is pushed to
`origin/validation/v0-baseline` per §10 (push allowed by normal workflow; merge deliberately **not**
performed — awaiting architecture review). Worktree clean after the commit. Two scratch harnesses are
kept under `docs/validation/v0/` as evidence and are outside pytest's collection root.

## W. V1 readiness

Not begun. V1 waits on the W-2 decision (§G). Everything else this closure was asked to establish is in place: a deterministic 5.1 guard that bites, a deterministic idempotency test that still tests scoping, and a full backend run whose result is recorded above exactly as produced.

**VERDICT: V0 CONDITIONAL — REVIEW REQUIRED** — the suite is clean, but W-2 stopped at the §2A condition and awaits the reviewer's decision (§G).
