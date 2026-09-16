# ACT Enterprise Validation Gate — V0 Evidence Bundle

**Phase:** V0 — Baseline Integrity, Fixture Cleanup & Reproducibility (post-Milestone 5).
**Date:** 2026-09-17. **Branch:** `validation/v0-baseline` (cut from `main` at `9667707`).
**Authority for every number below:** the live repository, the live PostgreSQL database and the
actual runs recorded in this directory. Historical tracking files were compared against, never
trusted. No number here was written before the run that produced it completed.

Raw run logs live next to this file (see the index at the end).

## A. Executive verdict

**VERDICT: V0 CONDITIONAL — REVIEW REQUIRED.**

Everything V0 set out to verify was verified from live state, and the reported 5.5 fixture defect was
independently confirmed, truthfully corrected, its residue removed, and its elimination proven by 50
consecutive clean runs against a measured pre-fix failure rate of 6%. Migration state, schema, routes,
frontend, TypeScript, build, tenant isolation, truthful control and cryptographic identity are all green.

V0 is not a clean PASS for one reason that is reported rather than hidden: the post-fix full regression
produced **2,639 passed / 1 failed / 1 deselected**, and the one failure is a *second, previously
unrecorded* probabilistic test-infrastructure defect (W-7: the 5.1 duplicate detector blocking a test
that names two same-org agents `Agent <6 hex>`, ~5.4% per run). The prompt authorizes exactly one fixture
correction, forbids re-rolling for a better number, and requires "full backend clean" for a PASS. The
defect is fully diagnosed with a one-line proposed fix; applying it and re-running is the reviewer's call.
Two further items need review: W-2 (a native agent can be transitioned out of GOVERNED by a privileged
actor — an invariant gap found by the §9B trace, no data affected) and the two proposals (§J, §T).

## B. Starting repository state (Phase 0, captured before any change)

| Item | Live value |
|---|---|
| Branch | `main` |
| Local HEAD | `966770711c169265e2bf671dbb7d423f74d83d80` |
| `origin/main` (after `git fetch`) | `966770711c169265e2bf671dbb7d423f74d83d80` — equal |
| Worktree | clean: 0 staged, 0 unstaged, 0 untracked |
| Unexpected commits | none — top of log is the Phase 5.10 merge, as reported |
| Validation branch state | none existed; `validation/v0-baseline` was created *after* the pre-fix baseline |
| Dev server on `:8002` | none listening (the `docs/testing/strategy.md` interference case ruled out) |

Repository state was expected; no STOP condition.

## C. Mechanically verified repository truth (§6)

| Item | Live | Tracking claim | Classification |
|---|---|---|---|
| Migration files | 61 (`0001`…`0061`) | REPO_STATE: head `0061_assurance_evidence` | LIVE CORRECT |
| Alembic script heads | exactly one: `0061_assurance_evidence` | same | LIVE CORRECT |
| Live `alembic_version` | `0061_assurance_evidence` | same | LIVE CORRECT |
| Live public base tables | 152 (151 + `alembic_version`) | REPO_STATE 5.10 delta: 152 / 151 in metadata | LIVE CORRECT |
| `Base.metadata` tables | 151; metadata − live = none, live − metadata = {`alembic_version`} | same | LIVE CORRECT |
| API routes (`app.routes` with methods) | 676 | REPO_STATE 5.10 delta: 676 | LIVE CORRECT |
| Backend collection | 2,641 collected, 1 deselected (`live_provider`), 2,640 selected | REPO_STATE: "2,640 collected" | LIVE CORRECT — REPO_STATE's figure is the *selected* count; pytest prints `2640/2641`. COUNT DRIFT in wording only |
| Frontend test files | 52 files | — | executed count in §N |
| ADRs | 22 (`0001`…`0022`) plus README and template in `docs/architecture/adr/` | — | recorded |
| Docs | 191 markdown files under `docs/` | — | recorded |
| README "Where the project is now" table (`README.md:45-48`) | — | 2,385 backend / 359 frontend / 141 tables / head `0055_agent_discovery` / 603 routes | **LIVE CORRECT / DOC STALE** — last regenerated at Phase 5.2; README defers to REPO_STATE as the authority (lines 38-41) |
| README "Running tests" (`README.md:1218-1240`) | — | 1,575 backend / 297 frontend | **LIVE CORRECT / DOC STALE** (Phase-1-era figures) |
| README project-structure comment (`README.md:159`) | — | "119 tables" | **LIVE CORRECT / DOC STALE** |
| CHANGELOG top entry | Phase 5.10 `[Unreleased]` | — | consistent with HEAD |
| RECOVERY | "Last verified 2026-09-16", head `0061`, 152 tables | — | LIVE CORRECT |
| Toolchain | Python 3.13.14 (venv), Node v24.18.0, npm 11.16.0, PostgreSQL 17.10 | — | recorded |
| CI | **none** — no `.github/`, no workflow files | — | recorded (§T) |

Nothing was silently reconciled; the stale README figures are handled in §U.

## D. Database / schema truth (§7)

- Connectivity OK. `PostgreSQL 17.10 on x86_64-windows`, database `ai_agent_control_tower`; user and password redacted.
- Migration head agrees with the script head (single head `0061_assurance_evidence`).
- Schema consistency: every `Base.metadata` table exists live; no live table is unknown to metadata.
- M5 canonical-agent schema present on `agents`: `control_state`, `origin_category`, `origin_provider`,
  `first_observed_at`, `last_observed_at`, `discovery_source_ref`, `discovery_confidence`,
  `external_enforcement_mode`, `row_version`; CHECKs `ck_agents_control_state`,
  `ck_agents_origin_category` (migration `0054`) and `ck_agents_external_enforcement_mode` (`0060`).
- Discovery tables: `discovery_sources`, `discovery_runs`, `discovery_observations`, `discovery_findings`.
- Graph, findings, external-governance (`external_capability_grants`, `external_request_nonces`,
  `external_gateway_calls`) and assurance-evidence tables: present (metadata = live).
- M4.11 state: `signing_keys` 42,705 rows (42,342 ACTIVE / 363 REVOKED, all ED25519),
  `signing_key_versions` 42,949; `installation_bootstrap` and `key_material_canary` are
  test-managed singletons (0 rows between runs; the M4.11/M4.11a suites create and clean them).
  No key material was read or printed.
- Agents population at start: **100,069** rows. Distribution (origin_category × control_state):
  EXTERNAL/CLAIMED 153, EXTERNAL/DISCOVERED 6,366, EXTERNAL/GOVERNED 28, EXTERNAL/REGISTERED 106,
  **NATIVE/DISCOVERED 16**, NATIVE/GOVERNED 93,335, UNKNOWN/DISCOVERED 50, UNKNOWN/GOVERNED 15.
  NATIVE rows with `origin_provider` other than `ACT_NATIVE`: 0.
- 36 foreign keys reference `agents.id`; 46 `agent_id`-like columns were checked for residue references (§I).

## E. Pre-fix baseline (§8) — frozen tree, frozen database

| | |
|---|---|
| Command | `.venv/Scripts/python.exe -m pytest -q -ra` (from `backend/`) |
| Commit / tree | `9667707`, `main`, 0 dirty entries; no edit, no git mutation, no DB write by the validator during the run |
| Start / end | 2026-09-17 00:19:05 → 00:46:01 (+05:00) |
| Environment | Python 3.13.14, PostgreSQL 17.10; notifications, rate limiting and the response envelope forced off by `tests/conftest.py` |
| Result | **2,640 passed, 0 failed, 0 skipped, 1 deselected, 0 xfailed, 0 xpassed, 16,685 warnings, 1612.79 s (26:52)** |
| Known failure | **did not occur** in this run |

Per §8 this is not evidence the flake is gone. It was therefore characterized by repetition on the
still-frozen tree and database (`prefix_rate.log`): the 5.1 guard alone, 50 consecutive invocations,
**3 failures / 50 (6%)** at runs 2, 7 and 30, about 23 s each. One exact failing traceback was then
captured (`prefix_failure_traceback.log`, attempt 2):

```
tests/runtime/test_agent_asset_model.py:429: AssertionError
>                   assert a.control_state == "GOVERNED"
E                   AssertionError: assert 'DISCOVERED' == 'GOVERNED'
FAILED tests/runtime/test_agent_asset_model.py::test_ac09_existing_agents_are_backfilled_native_and_governed
```

Warnings: dominated by third-party `datetime.utcnow()` deprecations (python-jose, onelogin/SAML),
a `websockets.legacy` deprecation via uvicorn, one passlib/argon2 deprecation, and one FastAPI
`UserWarning: Duplicate Operation ID update_policy_po…` (pre-existing, W-3). None originate in
repository code.

**Causal proof from the baseline itself.** The baseline started with 16 invalid rows and ended with
**17**: `agent-452ea2da`, created 2026-09-17 00:31:20, inside the run window, by the unmodified
fixture. The 17th row is the defect reproducing itself under observation.

## F. 5.5 fixture diagnosis (§9)

1. **Helper:** `backend/tests/posture/test_security_posture.py:46` — `_insert_agent(db, admin, *, name=None,
   control_state="GOVERNED", origin_category="NATIVE", origin_provider="ACT_NATIVE", lifecycle_status="ACTIVE",
   owned=True, discovery_source_ref=None)`; a raw `INSERT INTO agents` with `api_key_hash='x'` and
   `name = f"agent-{aid.hex[:8]}"`.
2. **Call sites (21):** four pass `control_state="DISCOVERED"`. Lines 370, 397 and 838 also pass an explicit
   non-native origin (EXTERNAL/MICROSOFT, UNKNOWN/UNKNOWN, EXTERNAL/MICROSOFT). **Line 282
   (`test_ac02_rules_are_deterministic`) is the only call that passes DISCOVERED and lets `origin_category`
   default to NATIVE.** A second `_insert_agent` in `tests/threat/test_runtime_threat_containment.py:47` has
   the same NATIVE default; its one DISCOVERED call (line 1069) passes `origin_category="EXTERNAL"` (W-4).
3. **Model defaults** (`app/models/agent.py:185-203`): `control_state` GOVERNED, `origin_category` NATIVE,
   `origin_provider` ACT_NATIVE, each as both ORM default and server default. Comment: "Native rows are
   GOVERNED and may be in any lifecycle_status."
4. **The M5.1 invariant** (`tests/runtime/test_agent_asset_model.py:417-432`): `db.query(Agent).limit(500)`,
   then per row: enum membership, and `origin_category == "NATIVE"` implies `control_state == "GOVERNED"` and
   `origin_provider == "ACT_NATIVE"`. The database carries only the two enum CHECKs; **no cross-column CHECK**.
5. **Migration/backfill:** `0054_agent_asset_model` adds the columns with server defaults GOVERNED / NATIVE /
   ACT_NATIVE, so every pre-5.1 row was backfilled valid; it creates only the enum CHECKs.
6. to 8. **Rows, provenance, fixture origin:** §G.
9. **Production path:** §G (§9B) — production cannot create the combination.
10. **5.10 or later:** the Phase 5.10 suite created none; the rows at 2026-09-16 16:48 and 17:31 were created
    by this same posture test during 5.10's two full runs.
11. and 12. **Sampling:** `LIMIT 500` with no `ORDER BY` over about 100k rows makes the sampled window a
    heap-order property. With 16 to 17 invalid rows the guard failed 3 of 50 attempts. Nondeterministic
    selection is confirmed as the mechanism that turns a present violation into an intermittent failure (§J).

## G. Invalid-row provenance analysis (§9A) and the production-path determination (§9B)

### §9A — mechanical classification of every invariant-violating row

Enumeration query (read-only, run before any modification; `enum_invalid.py`):

```sql
SELECT a.id, a.organization_id, o.name, a.name, a.origin_category, a.origin_provider, a.control_state,
       a.lifecycle_status, a.owner_id, a.owner_type, a.discovery_source_ref, a.external_reference,
       a.api_key_hash, a.created_at
FROM agents a LEFT JOIN organizations o ON o.id = a.organization_id
WHERE a.origin_category = 'NATIVE'
  AND (a.control_state <> 'GOVERNED' OR a.origin_provider <> 'ACT_NATIVE' OR a.origin_provider IS NULL)
ORDER BY a.created_at;
```

Result: **16 rows** at the start of V0 (17 after the pre-fix baseline; the 17th is the causal proof in §E).
Every row, without exception:

| Signal | Value on all 16/17 rows | Fixture comparison |
|---|---|---|
| `name` | `agent-` + first 8 hex of the row's **own** `id` | exactly `f"agent-{aid.hex[:8]}"` in `_insert_agent` |
| `api_key_hash` | `'x'` | the helper's literal; product creation stores a real hash (`record_external_agent` stores `''`) |
| `origin_provider` | `ACT_NATIVE` | helper default |
| `owner_id` / `owner_type` | NULL / NULL | `owned=False` at line 282 |
| `discovery_source_ref`, `external_reference` | NULL / NULL | helper default / not set |
| `lifecycle_status` | ACTIVE | helper default (product `record_external_agent` sets DRAFT) |
| organization | a distinct org named **"Posture Org"** containing **exactly one** agent, whose only user is `posture_<hex10>@example.com` | `tests/posture/conftest.py:48,67` registers exactly that org per test |
| `created_at` | 2026-09-10 16:53 … 2026-09-17 00:31 (11 hourly buckets) | every bucket lies minutes to an hour **before a phase commit** (5.5 at 09-10 17:45, 5.6 at 09-14 16:17, 5.7 at 09-15 17:58, 5.8 at 09-16 02:31, 5.9 at 04:10, 5.10 at 17:49) or inside this session's baseline window; **none predates 5.5 development**, when the fixture first existed |
| audit linkage | **zero** `audit_logs` rows reference any of the ids, by `entity_id` or in `metadata` — while the product path emits `AGENT_CREATED` (4,305 such rows exist) | consistent only with a raw SQL insert |
| discovery linkage | zero `discovery_findings` rows; `discovery_observations` has no agent linkage column | not produced by 5.2 |
| negative control | rows **not** matching the fixture name pattern: **0** | no unexplained row |

Classification: **17 / 17 `TEST RESIDUE (fixture-attributable)`. 0 `PRODUCT-PATH ORIGIN`. 0 `UNKNOWN PROVENANCE`.**

### §9B — can production create NATIVE + DISCOVERED? **No.**

Every writer of `origin_category` / `control_state` in `backend/app/` was traced (`grep` over assignments,
raw SQL, and write schemas):

| Path | Writes | Can it yield NATIVE + DISCOVERED? |
|---|---|---|
| `AgentProvenanceService.record_external_agent` (`app/runtime/registry/control.py:97-165`) — **the only writer of `control_state='DISCOVERED'`** | `control_state="DISCOVERED"`, `origin_category=<arg>` | **No** — it raises `VALIDATION_ERROR` unless `origin_category in ("EXTERNAL", "UNKNOWN")` (line 119) |
| `ReconciliationService` (`app/discovery/reconciliation.py:135-145`) | calls the above with `origin_category="EXTERNAL"` | No |
| `AgentControlStateService.claim` (`control.py:236`) | `DISCOVERED → CLAIMED` only | No (never writes DISCOVERED) |
| `AgentControlStateService.transition` (`control.py:280-330`) | matrix `CONTROL_TRANSITIONS` (`control.py:77-82`): DISCOVERED→{}, CLAIMED→{REGISTERED}, REGISTERED→{GOVERNED, CLAIMED}, GOVERNED→{REGISTERED} | No — **no transition targets DISCOVERED** |
| Native agent creation (registry) | model/server defaults GOVERNED / NATIVE / ACT_NATIVE | No |
| 5.7 bridge (`app/bridge/*`) | `external_enforcement_mode` only; never `control_state` or `origin_category` | No |
| Write schemas (`app/runtime/registry/schemas.py:157-160, 224-253`, `app/bridge/schemas.py`) | `control_state` / `origin_category` appear **only in read models**; "never accepted on a write" | No client path |
| Raw SQL `UPDATE agents` / `INSERT INTO agents` in `app/` | **none exist** | No |
| Migration/backfill (`0054`) | server defaults, valid combination | No |

**Determination: the diagnosis is confirmed as a test-data defect.** Only the raw-SQL test helper bypasses
the service invariant. V0 proceeds to §H.

**Adjacent finding surfaced by the same trace (W-2, not the DB-observed combination):** the generic
transition endpoint `POST /api/v1/runtime/agents/{id}/control-state` (`app/runtime/routes.py:495-501`)
does not consult `origin_category`, and the matrix allows GOVERNED→REGISTERED→CLAIMED. A caller holding
`control.manage` could therefore move a **NATIVE** agent to REGISTERED or CLAIMED — states the model comment,
the 5.1 guard (`NATIVE ⇒ GOVERNED`) and 5.6's containment gate (`control_state == GOVERNED` is the only
enforceable state) all treat as impossible for a native agent. The live database contains **zero** such rows
(distribution in §D), so nothing has exercised it; it is recorded as a defect for review, not fixed in V0
(§X), because it is an invariant/architecture question, not a fixture.

## H. Exact correction made (§11)

| | |
|---|---|
| FILE | `backend/tests/posture/test_security_posture.py` |
| REASON | `test_ac02_rules_are_deterministic` inserted a DISCOVERED agent on the helper's NATIVE / ACT_NATIVE default — a combination production cannot produce (§9B) and the 5.1 guard forbids |
| BEFORE (line 282) | `aid = _insert_agent(db, admin, owned=False, control_state="DISCOVERED")` |
| AFTER | `aid = _insert_agent(db, admin, owned=False, control_state="DISCOVERED", origin_category="UNKNOWN", origin_provider="UNKNOWN")` plus a four-line comment stating why |
| WHY `UNKNOWN`, not `EXTERNAL` (§10A) | The test establishes **no** provenance evidence: no source, no provider, no external reference. The live enum (`ORIGIN_CATEGORIES`, `control.py:56`) defines `EXTERNAL` as "exists outside ACT (real evidence required — 5.2 provides it)" and `UNKNOWN` as "seen but not yet classified". Asserting EXTERNAL would claim provenance the test never established; UNKNOWN is the value that is *true*. It also mirrors the same file's own precedent at line 397 (`test_ac06_rule_set_fires`). `origin_provider="UNKNOWN"` accompanies it because `ACT_NATIVE` on an UNKNOWN row would be a second internal contradiction. A truthful value exists, so the §10A "STOP" branch does not apply |
| Effect on the test's assertions | It asserts a re-evaluation opens 0 new findings and that `no_accountable_owner` and `discovered_outside_lifecycle` are among the open findings — both hold; `unknown_provenance` now additionally fires (correctly, for an UNKNOWN agent), and the determinism assertion is stronger for it |
| Affected tests | `test_ac02_rules_are_deterministic` only (call site); the 5.1 guard `test_ac09_…` indirectly (no more residue is produced) |
| Before behaviour | every run of the posture suite left one NATIVE+DISCOVERED row in the shared DB; the 5.1 guard then failed with probability proportional to the residue count (measured 6% at 17 rows) |
| After behaviour | the posture suite leaves an UNKNOWN+DISCOVERED row (a legal state); the guard's population contains no violation |
| TEST EVIDENCE | §K, §L, §M |

No production code, invariant, enum, migration or 5.1 behaviour was touched.

## I. Residue cleanup performed (§12) — after the §8 baseline, never before

- **Query used** (`cleanup_residue.py`): rows are selected by the **full fixture signature at once**, not by the
  invariant alone: `origin_category='NATIVE' AND control_state='DISCOVERED' AND origin_provider='ACT_NATIVE'
  AND api_key_hash='x' AND name = 'agent-' || left(replace(id::text,'-',''),8) AND owner_id IS NULL AND
  owner_type IS NULL AND discovery_source_ref IS NULL AND external_reference IS NULL AND organizations.name =
  'Posture Org'`.
- **Guards asserted before deleting:** (a) the count of invariant-violating rows equals the count matching the
  full signature (17 = 17 — had any invalid row *not* matched the fixture signature the script stops);
  (b) zero rows in any of the 46 `agent_id`-like columns across the schema reference the ids; (c) the deleted
  row count equals the enumerated count.
- **Found:** 17. **Classification:** 17 `TEST RESIDUE (fixture-attributable)`, 0 other.
- **Deleted:** 17 (ids listed in `cleanup_residue.log`). Transactional; no cascade was needed because nothing
  referenced them.
- **Post-cleanup verification:** re-running the invariant enumeration returns **0**; `agents` count
  105,330 → 105,313. No organization, user, finding, or product row was touched.

## J. Deterministic invariant-guard analysis (PROPOSAL ONLY — not implemented)

**Current query** (`backend/tests/runtime/test_agent_asset_model.py:417-432`):
`db.query(Agent).limit(500).all()` then, per row: control_state in the four states, origin_category in the three categories, and `NATIVE ⇒ (control_state == GOVERNED and origin_provider == ACT_NATIVE)`.

**Why nondeterministic.** `LIMIT 500` with no `ORDER BY` over ~100k rows: Postgres returns whichever 500 rows the planner's sequential scan reaches first (heap order, affected by vacuum, updates, HOT chains and concurrent inserts). Whether one of the invalid rows is in that window is therefore a property of the heap, not of the invariant. An invariant violation that *exists* is reported only sometimes; a suite whose failure depends on physical row placement is not a validation instrument.

**Options**
1. `ORDER BY created_at, id LIMIT 500` — deterministic, but still samples: with ~100k rows it would inspect the *oldest* 500 (all pre-5.1 backfilled rows) and would never see any newer violation. Deterministically blind.
2. Full-population invariant query — `SELECT count(*) FROM agents WHERE origin_category='NATIVE' AND (control_state<>'GOVERNED' OR origin_provider<>'ACT_NATIVE')` asserted `== 0`, plus the same shape for the enum checks (redundant with the DB CHECKs). Cost measured in this session: a single aggregate over 100,069 rows, index on control_state exists; sub-second. Sees every row, every run, deterministically.
3. DB-level CHECK constraint, e.g. `ck_agents_native_is_governed`: `NOT (origin_category='NATIVE' AND control_state<>'GOVERNED')`. Makes the state unstorable, by any path including raw test SQL. Requires a migration (out of V0 scope, §18) and the residue cleaned first (a CHECK cannot be added while violating rows exist). Interaction flagged: §9B found the *generic* transition endpoint can move a NATIVE agent GOVERNED→REGISTERED (see W-2); a CHECK would turn that request into a 500 (IntegrityError) rather than a governed refusal, so the endpoint must be hardened *first* or in the same change.
4. Targeted invalid-state query — same as option 2 restricted to the NATIVE⇒GOVERNED clause only.

**Recommendation.** Option 2 now (test-only change, no migration, deterministic, full coverage, sub-second), and option 3 as a follow-on architectural change *after* W-2 is decided, because a constraint is the stronger guarantee but is not merely a test improvement here. Option 1 is rejected: it trades a random blind spot for a fixed one.

**Not implemented.** Requires explicit approval.

## K. Targeted regression (§14) — after the fix and cleanup

| | |
|---|---|
| Command | `pytest -q -ra tests/posture tests/runtime/test_agent_asset_model.py tests/discovery tests/graph/test_control_graph.py` |
| Scope | 5.5 posture (incl. the corrected `test_ac02`), 5.1 asset model (invariant guard `test_ac09`, claims, transitions, concurrency, tenancy), 5.2 discovery/reconciliation (origin/control-state derivation, hostile-source tenancy), 5.3 control graph (ownership/authority chains, tenant boundary) |
| Result | **133 passed, 0 failed, 766 warnings, 139.21 s** (01:07:30 → 01:09:53) |
| Log | `targeted_regression.log` |

## L. Full backend regression (§15) — post-fix, post-cleanup, frozen tree

| | |
|---|---|
| Command | `.venv/Scripts/python.exe -m pytest -q -ra` from `backend/` |
| Tree | commit `9667707` on `validation/v0-baseline`; working tree = the one fixture edit, untouched for the run's duration |
| Start / end | 01:10:06 → 01:34:51 (+05:00) |
| COLLECTED | 2,641 (2,640 selected) |
| PASSED | **2,639** |
| FAILED | **1** — `tests/authorization/test_runtime.py::test_idempotency_is_scoped_per_agent_not_shared` |
| SKIPPED | 0 |
| DESELECTED | 1 (`live_provider`) |
| XFAILED / XPASSED | 0 / 0 |
| WARNINGS | 16,672 (same third-party sources as §E) |
| DURATION | 1482.31 s (24:42) |
| Posture guard `test_ac09` | **passed**; invariant enumeration after the run: **0** violating rows; the corrected posture test left an `UNKNOWN`/`DISCOVERED` row (legal) |
| Log | `full_regression_postfix.log` |

The one failure is **not** the posture flake and **not** caused by V0's changes; it is a second, previously
unrecorded probabilistic test-infrastructure defect (W-7, §W) whose mechanism was reproduced arithmetically
from the product's own scoring formula. It was **not re-rolled**: §15/§16 forbid re-running for a better
number, and the number is reported as produced. It was re-run ten times standalone (five on this tree, five on
the stashed, unmodified tree): 10/10 passed, consistent with a ~5% probability event, and proving it is
pre-existing and independent of the fixture change (`idempotency_flake_reruns.log`).

## M. Repeatability / flake-elimination proof (§16)

| | |
|---|---|
| What was repeated | the 5.5 posture suite (`tests/posture/test_security_posture.py`, 31 tests incl. the corrected `test_ac02`) **plus** the 5.1 invariant guard `test_ac09_existing_agents_are_backfilled_native_and_governed` — 32 tests per iteration, each iteration a fresh `pytest` process |
| Tree / DB | corrected tree (the one fixture edit), residue-free database, shared dev DB growing normally under the suite (100,069 → 112,010 agents over the session) |
| Runs | **50 consecutive** (01:42:55 → 02:26:35) |
| Result | **50 passed / 0 failed** — every iteration `32 passed`; average 52.4 s, max 72 s (`repeat50.log` records run number, rc, duration, summary per run) |
| Pre-fix comparison | same guard, same frozen pre-fix DB: **3 / 50 failed (6%)** (`prefix_rate.log`) |
| Post-loop enumeration | invariant-violating rows: **0** (`NATIVE` appears only with `GOVERNED`, 104,260 rows) |

**Confidence.** If the flake were still present at the *measured* pre-fix rate of 6%, the probability of 50
consecutive passes by chance is 0.94⁵⁰ ≈ **4.5%** (≈ 95.5% confidence it is gone); at the *reported* 8% it is
0.92⁵⁰ ≈ **1.5%** (≈ 98.5%). More decisively than either statistic: the population the guard samples now
contains **zero** violating rows and the only producer of such rows no longer produces them, so the residual
probability is not a sampling question any more. No run was discarded or re-rolled; the loop was bounded at 50.

## N. Frontend / TypeScript / build (§17)

| | |
|---|---|
| Commands | `npm test` (`vitest run`), `npx tsc -b --noEmit`, `npm run build` (`tsc -b && vite build`) — from `frontend/` |
| Toolchain | Node v24.18.0, npm 11.16.0 |
| Tests | **52 files, 384 passed, 0 failed**, 54.53 s |
| TypeScript | `tsc -b --noEmit` exit 0 (clean) |
| Build | exit 0, `✓ built in 2.54s` |
| Bundle warning | `(!) Some chunks are larger than 500 kB after minification` — pre-existing code-splitting debt, out of V0 scope |
| Node warning | `[DEP0190] DeprecationWarning: Passing args to a child process with shell option true…` — emitted by the 5.9 build-integrity test's `execFile(..., {shell: true})` under Node 24 (W-8, low, not changed) |
| **Guard bite** | The 5.9 fix (`export type { TraceContentResponse } from './observabilityService'`, `frontend/src/services/index.ts:19`) was temporarily removed and only `build-integrity.test.ts` run: it **failed** with `TS2305: Module '"@/services"' has no exported member 'TraceContentResponse'` (plus the two follow-on TS7006 errors). The file was restored with `git checkout` and the worktree verified. The guard is live, not decorative. `guard_bite.log` |
| Log | `frontend.log` |

## O. Migration verification (§18)

- Script heads: exactly one, `0061_assurance_evidence`; 61 revision files, walk completes with no branch.
- Live `alembic_version`: `0061_assurance_evidence` — agrees with the script head; `alembic upgrade head` would be a no-op.
- Metadata vs live schema: identical table sets (§C/§D).
- Reversibility: every migration in the M5 chain carries a `downgrade()`; the per-phase structural guards
  that assert additivity/reversibility (`test_ac01`/`ac13`-style guards in `tests/posture`, `tests/graph`,
  `tests/discovery`, `tests/bridge`, `tests/assurance`, `tests/threat`, `tests/runtime/test_key_material_integrity.py`)
  all passed in both full runs. A live downgrade/upgrade round-trip was **not** executed on the shared dev
  database: it would drop populated M5 tables and destroy the very population V0 characterizes.
- **No new migration was created**, as §18 requires; none was needed because §9B found no product-path origin.

## P. M4.11 / M4.11a safety verification (§19)

Run verbosely after all V0 changes (`safety_suites.log`, part A: **144 passed, 0 failed** across
`tests/runtime/test_key_material_integrity.py` (40 tests), `tests/threat`, `tests/bridge`, `tests/milestone`).
Named guarantees, each `PASSED`:

- installation bootstrap marker: `test_m411a_ac01_marker_is_a_durable_singleton_with_no_secret`, `test_m411a_ac07/ac08/ac09/ac10`
- fail-loud missing key: `test_ac01_missing_encryption_key_on_established_install_fails_loud`, `test_ac03_missing_signing_private_key_fails_loud`, `test_ac10_negative_restore_missing_key_never_regenerates`
- wrong-key detection: `test_ac02_wrong_encryption_key_fails_loud_and_is_deterministic`, `test_ac03_wrong_signing_private_key_is_a_mismatch`, `test_ac10_negative_restore_wrong_key_is_deterministic`
- key-provider seam: `test_ac11_encryption_key_provider_seam`, `test_ac11_core_imports_no_vendor_sdk`
- signing-key availability / established-install no-op: `test_ac15_valid_key_established_install_is_a_noop`, `test_ac07_and_ac09_positive_restore_proof`
- existing encrypted-credential readability: `test_ac13_existing_ciphertext_decrypts_unchanged`
- historical-signature verification: `test_ac08_historical_signatures_survive_key_loss_and_restore`
- no material leaks: `test_ac04_failure_messages_contain_no_secret`, `test_ac14_new_code_never_logs_or_prints_key_bytes`, `test_m411a_ac11_no_material_leaks_in_any_state`

**No cryptographic identity change occurred**: V0 wrote no key, marker or canary row; the only DB write was the
deletion of 17 unreferenced `agents` rows. No secret material was printed anywhere in this bundle.

## Q. M5 truthful-control verification (§20)

Existing tests run, not altered (`safety_suites.log`, part A). A truthful refusal is a PASS. Each `PASSED`:

| Property | Proof |
|---|---|
| discovered ≠ controlled; observed/advisory cannot falsely contain | `threat::test_ac05_observed_agent_containment_is_truthfully_refused[DISCOVERED]`, `[CLAIMED]`, `[REGISTERED]` |
| containment requires real authority; native routes to the real authority | `threat::test_ac05_governed_agent_containment_routes_to_the_real_authority`, `bridge::test_ac03_native_mode_routes_to_the_real_4_3_engine_and_kill_switch` |
| gateway enforcement limited to gateway authority; out-of-band is outside reach | `bridge::test_ac07_out_of_band_action_is_truthfully_outside_reach`, `bridge::test_ac07_denies_out_of_scope_call_and_says_what_it_cannot_reach` |
| native enforcement cannot be fabricated for external assets; no over-claim | `bridge::test_ac02_governed_agent_cannot_be_downgraded_to_a_weaker_claim`, `bridge::test_ac03_observed_agent_cannot_be_given_a_boundary_credential` |
| **an external kill remains REFUSED where ACT does not own the process** | `milestone::test_ac02_ac03_ac04_the_milestone_5_end_to_end_proof` (asserts `status == "REFUSED"` with "no enforcement authority"), `milestone::test_ac05_truthful_control…` |
| grant/capability revocation works where ACT holds authority | `bridge::test_ac10_revocation_is_immediate`, the E2E's re-run of the external process after revocation |
| kill-switch dominance; failed containment recorded honestly | `threat::test_ac06_reverting_a_kill_switch_action_is_refused`, `threat::test_ac06_kill_dominates_a_concurrent_containment_recommendation`, `threat::test_ac09_a_failed_containment_is_recorded_honestly_not_as_executed` |
| dangerous UI actions server-authorized | `command_center` affordance tests in the full run (§L) and the 5.8 structural tests in the frontend suite (§N) |

No false containment, no fabricated native authority, no fail-open regression observed.

## R. Tenant-isolation verification (§21)

`pytest -v -k "tenant or cross_org or other_org or isolation or leak"` across the whole suite
(`safety_suites.log`, part B): **112 passed, 0 failed, 2,529 deselected**. Coverage by domain, all `PASSED`:

- canonical agent access: `runtime/test_agent_asset_model.py` tenant tests; `authorization/test_runtime.py::test_kill_switch_cross_org_denied`
- discovery observations: `discovery::test_ac11_hostile_source_cannot_create_agents_in_another_tenant`
- ownership/claims + control graph: `graph/test_control_graph.py::test_ac06_authority_chain_cannot_cross_a_tenant_boundary` and siblings; `graph/test_dependency_graph.py` tenant tests
- findings / posture: `posture` tenant tests (`other_org_admin` 404 paths)
- external governance: `bridge` tenant tests
- assurance evidence: `assurance` tenant tests
- milestone per-hop adversarial isolation: `milestone::test_ac06_*` (both)
- existence-leak prevention: `runtime/test_milestone_4_proof.py::test_ac06_tenant_privacy_no_cross_tenant_metadata_content_or_existence_leak`

**No cross-tenant leak observed.** No P0.

## S. Reproducibility assessment (§22)

Can another engineer reproduce V0 from a clean checkout? **Mostly yes, with documentation gaps and one
environment-specific dependency.** No secrets are recorded here.

| Item | Live fact | Classification |
|---|---|---|
| OS / runtime assumed | Developed and validated on Windows 11 (`x86_64-windows` PostgreSQL build); `docker-compose.yml` provides `postgres:17-alpine`, `api`, `web` services for Linux containers | ENVIRONMENT-SPECIFIC (paths in README use both `\` and `/`; nothing OS-bound in the code) |
| Python | 3.13.14 in `backend/.venv`; pins in `backend/requirements.txt` (FastAPI 0.115.6, SQLAlchemy 2.0.36, Alembic 1.14.0, psycopg2-binary 2.9.10, pytest 8.3.4, uvicorn 0.34.0) | REPRODUCIBLE |
| Node | v24.18.0 / npm 11.16.0; `frontend/package-lock.json` present; Vite 8, vitest 2.1, TypeScript 6.0 | REPRODUCIBLE (no `engines` field in `package.json` → DOCUMENTATION GAP) |
| PostgreSQL | 17.10 local; compose pins `postgres:17-alpine` | REPRODUCIBLE |
| Dependency installation | `pip install -r requirements.txt`; `npm ci` | REPRODUCIBLE |
| Environment configuration | `backend/.env.example` documents every variable; `.env` is git-ignored; `DATABASE_URL`, `JWT_SECRET_KEY` required | REPRODUCIBLE (values are the engineer's own) |
| Test-DB setup | **There is no separate test database.** The suite runs against the same `DATABASE_URL` as the dev server (`docs/testing/strategy.md` "Operational note"); it accumulates rows (105k agents, 42k signing keys) across runs and depends on some pre-existing rows (`test_ac09` asserts the sampled population is non-empty) | DOCUMENTATION GAP + NON-DETERMINISTIC (state carried between runs is exactly what made the 5.1 guard probabilistic; a fresh DB has not been exercised in V0) |
| Migrations | `alembic upgrade head` from `backend/`; single head; URL injected from settings (`migrations/env.py`) | REPRODUCIBLE |
| Backend commands | `cd backend && pytest -q` (README "Running tests"; figures there are stale, §C) | REPRODUCIBLE; DOCUMENTATION GAP (stale counts) |
| Frontend commands | `npm test` (vitest run), `npx tsc -b --noEmit`, `npm run build` | REPRODUCIBLE |
| Required services | PostgreSQL only. SMTP, rate limiting, live model providers are forced off / deselected (`tests/conftest.py`, `pytest.ini`) | REPRODUCIBLE |
| Hidden/manual dependencies | (1) the dev server on `:8002` must be stopped during a run (documented); (2) the `live_provider` marker needs a local Ollama and is deselected by default; (3) the Phase 5.7/5.10 proofs bind real TCP sockets on localhost (`uvicorn`, `http.server`) and spawn a subprocess — a sandbox that forbids listening sockets breaks them; (4) Windows console code page: none of the test code depends on it, but this session's shell heredocs did | ENVIRONMENT-SPECIFIC (3), DOCUMENTATION GAP (1–3 are not in one place) |
| Run duration | backend ≈ 27 min, frontend ≈ 3–4 min on this workstation | recorded |

**Nothing is BLOCKING.** The two items that most affect an independent reproduction are the shared dev/test
database and the absence of CI (§T addresses both).

## T. Minimal CI — PROPOSAL ONLY (not implemented)

**Repository reality.** No `.github/` directory, no workflow files, no CI of any kind. The only automated build guard is `frontend/src/test/build-integrity.test.ts`, whose docstring explicitly says it exists *because* there is no CI. Tests run against the developer's dev database (`DATABASE_URL` from `backend/.env`; `docs/testing/strategy.md` operational note), with no dedicated test database.

**Proposed pipeline (evidence-integrity only)** — one workflow, one job matrix of two jobs:
- *backend*: checkout → Python 3.13 → `pip install -r backend/requirements.txt` → PostgreSQL 17 service container (`postgres:17-alpine`, the same image `docker-compose.yml` uses) → `DATABASE_URL` pointing at it, `JWT_SECRET_KEY` a throwaway → `alembic upgrade head` → assert single head → `pytest -q -ra --junitxml=backend.xml` → upload junit as artifact.
- *frontend*: checkout → Node 24 → `npm ci` → `npx tsc -b --noEmit` → `vitest run` → `npm run build` → upload junit/build log as artifact.
- Trigger: push to `main` and pull requests. No deploy, no release, no cloud resources, no secrets beyond the throwaway JWT secret and a throwaway DB password (both generated in the workflow, not stored).

**Benefit.** Every commit gets the exact numbers V0 had to derive by hand; the frozen-tree/frozen-DB problem disappears because each run is a fresh checkout on a fresh, empty database — which also removes the 100k-row accumulation that made the 5.1 guard probabilistic.
**Cost / runtime.** Backend suite locally: see §L duration; expect similar-to-longer on a 2-vCPU hosted runner. Frontend ~2–4 min. GitHub-hosted free tier (2,000 min/month for private repos, unlimited for public) suffices at a few runs per day.
**Platform.** GitHub Actions — the repository is already on GitHub; a Postgres service container is a first-class feature; no new vendor.
**PostgreSQL requirement.** 17.x service container (matches the supported version this session verified: 17.10). SQLite is *not* acceptable (concurrency/invariant tests, §7).
**Caveat.** A fresh, empty DB means tests that assert "pre-existing rows exist" (`test_ac09` asserts `rows` non-empty) will need review; that is the same test §J proposes to change. Await approval.

## U. Documentation / tracking changes (§24) — written only after every run completed

| FILE | REASON | BEFORE | AFTER | TEST EVIDENCE |
|---|---|---|---|---|
| `REPO_STATE.md` | record the V0 result separately from the M5 close | ends at the 5.10 delta | + a "Post-M5 Validation Gate V0" delta paragraph before §1; 5.10 delta untouched | §C figures re-derived live |
| `ROADMAP.md` | validation status | 5.10 "Next:" paragraph | + a "Post-M5 Validation Gate — V0" paragraph; the M5 status line untouched | — |
| `CHANGELOG.md` | validation entry | `[Unreleased]` = Phase 5.10 | new `[Unreleased] — Validation Gate V0` entry; 5.10 heading demoted to `[Phase 5.10 / M5.10]` per the file's convention; its text untouched | — |
| `RECOVERY.md` | note the only DB change (17 residue rows) and the crypto re-verification | "Last verified 2026-09-16" | + "Last verified 2026-09-17 after V0" paragraph; the M5 paragraph preserved | §P |
| `docs/validation/v0/*` | the evidence bundle and raw logs (this document) | did not exist | created | — |
| `backend/tests/posture/test_security_posture.py` | the §H correction | see §H | see §H | §K, §L, §M |

The M5 close (`2,639 passed / 1 failed / 1 deselected`) remains verbatim in all four tracking files; a
repository-wide search for test-count claims found the stale README figures (§C, W-5), which are
*intentional historical references* in a document that defers to REPO_STATE, and were left in place.

## V. Evidence bundle index (`docs/validation/v0/`)

| File | Content |
|---|---|
| `README.md` | this document (sections B–Z) |
| `baseline_prefix.log` | §E full pre-fix baseline, frozen tree/DB (`-q -ra` output, start/end, commit) |
| `prefix_rate.log` | §E 50× pre-fix guard runs (3 failures) |
| `prefix_failure_traceback.log` | §E one exact pre-fix failing traceback |
| `enum_invalid.log` | §G enumeration of the 16 initial invalid rows with all provenance columns (emails redacted) |
| `audit_link.log` | §G audit/discovery linkage and timestamp buckets |
| `cleanup_residue.log` | §I the 17 deleted ids, guards, post-cleanup zero |
| `fixture_fix.diff` | §H the exact change |
| `targeted_regression.log` | §K |
| `full_regression_postfix.log` | §L (includes the W-7 traceback) |
| `idempotency_flake_reruns.log` | §L/W-7 10× standalone re-runs on both trees |
| `repeat50.log` | §M 50 consecutive runs |
| `frontend.log` | §N tests / tsc / build |
| `guard_bite.log` | §N build-integrity guard proven live |
| `safety_suites.log` | §P/§Q/§R per-test verbose results |
| `dbtruth.py`, `enum_invalid.py`, `audit_link.py`, `cleanup_residue.py`, `repeat.sh` | the exact scripts, reproducible from `backend/` |

## W. Defects discovered

| # | DEFECT | SEVERITY | PRE-EXISTING / INTRODUCED | ROOT CAUSE | IMPACT | FIX / DEFER | EVIDENCE |
|---|---|---|---|---|---|---|---|
| W-1 | Posture fixture inserts NATIVE + DISCOVERED (`test_security_posture.py:282`) | Medium (test data; made the 5.1 invariant guard probabilistic) | Pre-existing since Phase 5.5 (2026-09-10) | `_insert_agent` NATIVE / ACT_NATIVE defaults combined with `control_state="DISCOVERED"` at one call site; raw SQL bypasses the service invariant | One invalid row per suite run in the shared DB; 5.1 guard failure rate measured 6% at 17 rows and rising | **FIXED** in V0 (§H) + residue cleaned (§I) | §E, §G, §K–§M |
| W-2 | Generic control-state transition does not consult `origin_category`; a NATIVE agent can be moved GOVERNED→REGISTERED→CLAIMED via `POST …/agents/{id}/control-state` by a holder of `control.manage` | Medium — invariant/architecture (a native agent ACT actually runs would then read as *not enforceable* to 5.6's containment gate: an under-claim, not an over-claim, but a truthfulness inversion the model comment says cannot happen) | Pre-existing since Phase 5.1 | `CONTROL_TRANSITIONS` (`control.py:77-82`) is origin-agnostic; `transition()` has no origin check | Not observed in data (0 NATIVE rows outside GOVERNED after cleanup); reachable only by a privileged actor; found by code trace, not executed (executing it would create the very residue V0 cleans) | **DEFERRED — review required** (§Y-1); also gates §J option 3 | `control.py:77-82, 280-330`; `routes.py:495-501`; §D distribution |
| W-3 | FastAPI `UserWarning: Duplicate Operation ID update_policy_po…` in OpenAPI generation | Low (cosmetic; OpenAPI operation ids collide) | Pre-existing | Two route handlers share a function name | Generated client code could collide on the operation id | DEFER (out of V0 scope) | baseline log, warnings summary |
| W-4 | Threat-suite `_insert_agent` (`test_runtime_threat_containment.py:47`) hard-codes `origin_provider='ACT_NATIVE'` even when called with `origin_category="EXTERNAL"` (line 1069) | Low (test data; does **not** violate the 5.1 guard, which checks only NATIVE rows; `ORIGIN_PROVIDERS` is informational and unenforced) | Pre-existing since Phase 5.6 | Helper omits an `origin_provider` parameter | Cosmetic inconsistency in test rows | DEFER — not part of the verified diagnosis; changing it is not needed for V0 | §F.2 |
| W-5 | Stale figures in `README.md` (lines 45-48, 159, 1218-1240) | Low (documentation) | Pre-existing | README summary not regenerated since Phase 5.2 | Misleading first impression; README itself defers to REPO_STATE | See §U | §C |
| W-7 | `test_idempotency_is_scoped_per_agent_not_shared` fails probabilistically (~5.4% per full run) because 5.1's duplicate detector scores its two same-org `Agent <6 hex>` agents as LIKELY duplicates — full write-up at the end of this section | Medium (blocks a single-run "full backend clean") | Pre-existing since 5.1's duplicate detection met this helper; never recorded | Helper naming + identical description/purpose vs `difflib` weighted ≥ 0.85 | One-in-~18 full runs fails on this test alone | **DEFERRED — proposal recorded, not applied** (§Y-1) | `full_regression_postfix.log`, `idempotency_flake_reruns.log`, Monte-Carlo in this section |
| W-8 | Node 24 `[DEP0190] DeprecationWarning` from `build-integrity.test.ts` (`execFile` with `shell: true`) | Low (warning only) | Pre-existing since 5.9 | `shell: true` needed to resolve `npx` on Windows | Noise in the frontend test output | DEFER | `frontend.log` |
| W-6 | Suite runs against the shared dev database with no dedicated test DB | Low–Medium (reproducibility / determinism) | Pre-existing (documented in `docs/testing/strategy.md`) | Single `DATABASE_URL` | Cross-run state accumulation is the substrate of W-1; independent reproduction starts from a different population | DEFER — §T proposal (fresh DB per CI run) | §S |

No P0 appeared: no cross-tenant leak, no false containment, no crypto identity change, no fail-open regression.

### W-7 — `test_idempotency_is_scoped_per_agent_not_shared` fails probabilistically on 5.1 duplicate detection (found by the §15 full regression)

**What happened.** The post-fix full regression (§L) failed exactly one test, and not the posture one:

```
tests/authorization/test_runtime.py:967  setup_b = _ready_agent(client, org)
tests/authorization/test_runtime.py:66   assert r.status_code == 200, r.text
E  AssertionError: {"success":false,"error":{"code":"AGENT_DUPLICATE_REVIEW_REQUIRED", ...
E  assert 409 == 200
```

**Root cause (from live code, reproduced arithmetically).** `_register_agent` (`test_runtime.py:48`) names every
agent `f"Agent {uuid.uuid4().hex[:6]}"` with the *same* description (`"A test agent."`) and business purpose
(`"Exercise the runtime in tests."`). Phase 5.1's `AgentDuplicateDetectionService` (`app/runtime/registry/
duplicates.py`) compares a registering agent against **every other agent in the organization**, scoring
`0.5 × name_ratio + 0.25 × description_ratio + 0.25 × purpose_ratio` with `difflib.SequenceMatcher`; a score
≥ 0.85 is a `LIKELY_DUPLICATE`, and `register()` (`services.py:105-113`) refuses with 409 until a reviewer
decides. With description and purpose identical (each 1.0), the block fires whenever the two random names
score ≥ 0.70. The pair that failed — `Agent cfbd5b` vs `Agent c8fd67` — has name ratio 0.75 → weighted
**0.875 ≥ 0.85**. A 200,000-pair Monte-Carlo with the product's own formula puts the per-pair probability at
**5.40%**. The detector is working exactly as specified; the test's naming scheme is what makes two of its
own agents look alike.

**Exposure.** An AST scan of `test_runtime.py` finds **exactly one** test that registers two or more agents in
the same organization: this one. So the whole suite carries a ~5.4% chance per full run of this failure,
independent of everything else. It is plausible it never surfaced in the recorded M5 runs (about 43% odds of
15 runs passing unseen), and no tracking file records it.

**Independence from V0's changes.** The test registers its own fresh organization; the V0 fixture change is in
`tests/posture/…` (a file this test never touches); the residue cleanup deleted rows only in single-agent
"Posture Org" tenants. Confirmed by re-running the test on the **stashed, unmodified** tree as well as the
current one (`idempotency_flake_reruns.log`).

**Classification.** Test-infrastructure defect, pre-existing since Phase 5.1's duplicate detection met this
helper; **not** a product defect, not architectural. It *directly prevents* the §15 "full backend clean"
criterion from being met on a single run without re-rolling — which §16 forbids.

**Proposed fix (NOT applied — §4 permits proposing test-infrastructure fixes, not applying a second one).**
In `tests/authorization/test_runtime.py:48`, give each test agent a name whose random part is long enough
that two of them cannot reach a 0.70 name ratio, e.g. `f"Agent {uuid.uuid4().hex}"` (32 hex chars: the shared
prefix "agent " is 6 of 38 characters; the Monte-Carlo ceiling for two full-hex names is far below 0.70),
or make the description/purpose unique per agent. The former is a one-token change, changes no assertion, and
removes the only same-org pair the suite creates. The Monte-Carlo was re-run for that naming in this session:
**0 LIKELY pairs in 200,000, maximum weighted score 0.8026** (still above the 0.72 non-blocking POSSIBLE
threshold because description and purpose stay identical, which is harmless). Adopting it must be followed by
a fresh full regression.

**Why not fixed silently.** The prompt authorizes exactly one fixture correction (the verified 5.5 one) and
residue cleanup; a second correction, however small, is a scope decision for the reviewer. Applying it would
also have required a further full regression to quote a clean number honestly.

## X. Changes deliberately NOT made

- **No production code changed.** The 5.1 invariant, enums, `CONTROL_TRANSITIONS`, transition endpoint,
  containment gate, tenancy, kill-switch and fail-closed semantics are untouched (W-2 deferred to review).
- **The 5.1 guard (`test_ac09`) was not modified** — proposal only (§J), per §13.
- **No migration, no DB CHECK constraint** — §18 forbids it in V0; §J documents it as the stronger follow-on.
- **No CI implemented** — proposal only (§T).
- **No test weakened, skipped, retried, or xfailed.** The fixture change strengthens the test's determinism claim.
- **README stale figures**: the "Where the project is now" table and "Running tests" figures were left as-is
  in this branch (they are prose that predates M5 and the README defers to REPO_STATE); the V0 result is
  recorded in the tracking files listed in §U. Correcting the README wholesale is a documentation task
  outside "tracking corrections based on actual results".
- **The threat-suite helper (W-4)** was not changed: it does not cause a guard failure and was not part of the
  verified diagnosis.
- **M5 history not rewritten**: the M5 close (`2,639 passed / 1 failed / 1 deselected`) stays exactly as
  recorded in ROADMAP / CHANGELOG / REPO_STATE / RECOVERY; the V0 baseline is recorded separately.
- **Nothing pushed, nothing merged**: the work is committed on `validation/v0-baseline` only.

## Y. Open questions requiring approval

0. **W-7** — approve the one-line naming change in `tests/authorization/test_runtime.py:48`
   (`f"Agent {uuid.uuid4().hex}"`, Monte-Carlo: 0 LIKELY pairs in 200,000, max weighted score 0.80) or the
   unique-description alternative, followed by a fresh full regression to quote a clean number. This is the
   item that turns CONDITIONAL into PASS.
1. **W-2** — should `AgentControlStateService.transition` refuse to move a NATIVE agent out of GOVERNED
   (or should the matrix be origin-aware)? Architecture decision; affects §J option 3.
2. **§J** — approve replacing the sampled `LIMIT 500` guard with the full-population invariant query
   (option 2), and whether to schedule the DB CHECK (option 3) after W-2 is decided.
3. **§T** — approve implementing the minimal CI workflow (GitHub Actions, Postgres 17 service container).
4. **Merge/push** of `validation/v0-baseline` into `main`.
5. Whether the README summary table should be regenerated now or with the next milestone doc pass.

## Z. V1 readiness

**Not authorized to begin, and not begun.** V1 (threat research, red-team, external agents, cloud,
organizations, M6) waits on: (1) a decision on W-7 and a subsequent clean full regression; (2) a decision
on W-2; (3) approval or deferral of §J and §T. The baseline substrate V1 needs — a truthful, reproducible,
residue-free repository whose invariant guards mean what they say — is otherwise in place on
`validation/v0-baseline`, committed and unmerged.

**VERDICT: V0 CONDITIONAL — REVIEW REQUIRED**
