# DT1 Stage 1 — The self-validator and its negative tests

`lab/dt1/validator.py` validates the **generated artifacts**, never ACT behaviour. It runs without a database and imports
nothing from `app`. Every check is named; a run exits non-zero if any check fails and lists every failure.
Evidence: [`evidence/validator_run.txt`](evidence/validator_run.txt) (65 checks, all pass on the sealed artifacts),
[`evidence/dt1_tests.txt`](evidence/dt1_tests.txt) (30 tests).

## Checks (65 on the sealed set)

| group | checks |
|---|---|
| schema validity | artifacts loadable; `estate_truth` top-level keys; every agent's required keys; contract and matrix structure |
| vocabularies vs the grounding | control_state, origin_category, lifecycle, enforcement mode, edge types, MCP trust status, reality class — all values must exist in `schema_grounding.json` |
| legality | control_state legal for origin (`LEGAL_CONTROL_STATES_BY_ORIGIN`); NATIVE ⇒ `ACT_NATIVE`; enforcement mode only for non-NATIVE; GATEWAY_ENFORCED ⇒ REGISTERED and known to ACT |
| identifiers | agent ids unique; names unique per tenant; every id matches `<kind>-<20 hex>`; all ids globally unique |
| referential integrity | owners, identity, credentials, tools, MCP servers, resources, sources, memory store, grant targets, shared-grant agent, credential owners/resources, tool credential/MCP/resources, MCP tools, dependency endpoints, delegation persons, A2A/authority endpoints, source listings, reachability endpoints — every reference resolves |
| tenant isolation | every reference stays inside the referencing entity's tenant; exactly one PRIMARY and one ISOLATION_CONTROL tenant |
| control group | 10–15 agents; ids consistent; all three owners; zero serious conditions; ACTIVE lifecycle; the estate is neither all-healthy nor all-risky; 50–60 canonical agents |
| adversarial presence | fourteen required condition classes present; F6-1 / I-1 / I-2 represented **where the grounding says the gap is PRESENT**; truthful-refusal subjects real (process not ACT's, grant held, real-process reality class); collision objective |
| Stage-2 markings | gateway-enforced / shared-grant / A2A-crossing agents are `ACTIVE_REAL_PROCESS_REQUIRED_STAGE2`; at least one discovery source crosses a process boundary and lists agents; sources list only agents that declare them |
| no expectations / no secrets / no real data | no `EXPECTED_*` / `ACT_SHOULD*` / `finding*` / `verdict*` keys in truth; no secret-shaped strings (patterns copied from the product scrubber); credentials carry no value; no PHI markers; `.example` emails only |
| contract | five classes only; every non-OBSERVE entry has code refs + justification + a boundary/precondition; no weakness-only justification; gap ids grounded; example agents exist; all five classes covered; generator matches truth |
| matrix | one row per agent; conditions and control flag match truth |
| canonical + determinism | re-serialization equals bytes on disk for all three artifacts; regeneration from the seed reproduces truth, contract and matrix byte-identically |
| seal | recomputed hashes equal the anchor; the anchor's timestamp and root are absent from hashed content; anchor versions match |
| boundary | only the allowed artifact files exist; no ACT execution artifact keys; `git diff <base_commit> -- backend/app backend/migrations backend/requirements.txt backend/tests frontend .github` is empty |

## Negative tests — the validator can fail (`lab/dt1/tests/test_negative.py`, 16 tests)

Each mutates a copy of the sealed artifacts and asserts the named check fails: duplicate canonical agent · missing owner
reference · invalid credential reference · invalid MCP reference · cross-tenant relationship · control group below ten ·
control group inflated with risky agents · a required adversarial condition removed (collision) · truthful-refusal scenario
removed · non-deterministic artifact (a wall-clock field breaks regeneration identity) · `estate_truth` tampered by one byte
after sealing · `observability_contract` tampered after sealing · a real-looking secret inserted (assembled by concatenation)
· an `EXPECTED_*` key inserted · forbidden real-data shapes (a real email domain, a PHI-named resource) · a production diff
violation (a temporary git repository whose `backend/app` differs from its base commit).

## Boundary tests (`test_boundaries.py`, 7 tests)

Production ACT imports nothing from DT1 (AST over `backend/app/**`); every DT1 module except `grounding.py` imports nothing
from `app` (and `grounding.py` imports exactly `app.main` + `app.core.database`, read-only); no DT1 module imports
SQLAlchemy/psycopg2/alembic; the production diff against `BASE_COMMIT` is empty; the migration head is unchanged at
`0061_assurance_evidence`; nothing was written into `backend/.keys/`; no forbidden markers.

## Running

```
backend/.venv/Scripts/python lab/dt1/cli.py validate
backend/.venv/Scripts/python -m pytest lab/dt1/tests -q
```
