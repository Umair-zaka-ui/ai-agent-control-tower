# REGRESSION — full suite, build, and the scoped product diff

## Baseline (live, before the phase)

`d7d0369` (tip of `validation/v7-interop`; `main` untouched at `9667707`), worktree clean. Head
`0061_assurance_evidence`; 152 tables live / 151 in `Base.metadata`; routes 676 (672 excluding the four doc
paths); collection **2,649 → 2,648 selected / 1 deselected**; frontend 384. (`evidence/live_counts.txt`.)

## Backend — two full runs

| run | tree | result | duration | evidence |
|---|---|---|---|---|
| 1 | adapter + tests + ADR/docs (before the fixture-literal concatenation and the two tracking paragraphs) | **2,680 passed / 1 failed / 1 deselected** (2,682 collected = 2,649 + 33 new) | 0:26:57 | `evidence/full_backend_run1.txt` |
| 2 | **final committed tree** | **2,681 passed / 0 failed / 1 deselected** (2,682 collected) | 0:25:45 | `evidence/full_backend_run2.txt` |

Collection grew by exactly the 33 new adapter tests. No test was skipped, xfailed, loosened, or deleted.

### The one run-1 failure — pre-existing probabilistic fixture defect, verified by stashing, left in place

`tests/runtime/test_operations_center.py::test_the_overview_does_not_scale_its_query_count_with_row_count`
failed with `assert 409 == 200` on the **second** `POST /api/v1/runtime/agents/{id}/register` inside its own
`_setup` helper. Characterization (per §4 of the brief: *verify any pre-existing flake by stashing + re-running
unmodified; leave it*):

- **Mechanism (product code, read):** `AgentRegistryService.register` runs 5.1's
  `AgentDuplicateDetectionService.check` against every other agent in the org; a weighted `difflib` similarity
  (`name×0.5 + description×0.25 + purpose×0.25`) at or above **0.85** records a `LIKELY_DUPLICATE`, which blocks
  registration with `409 AGENT_DUPLICATE_REVIEW_REQUIRED` until reviewed. The test's `_register_agent` names its
  agents `Ops Agent <8 hex>` / `Test agent <8 hex>.` / `Exercise the operations center <8 hex> in tests.` — the
  fixed prose dominates the two 25 %-weighted fields (typical ratios ≈ 0.67 / 0.70 / 0.88), so a lucky hex
  overlap in the name pushes the pair over the threshold. The `admin` fixture registers a fresh organization per
  test (`register_organization` constructs a new `Organization`), so the failing comparison is a single pair.
- **Rate, by the product's own formula:** 20,000 simulated pairs → **35 blocking (0.17 %)**, 64 % "possible"
  (warn-only), max score 0.8639 (`evidence/flake_montecarlo_operations_center.txt`). One failure in one full run
  is an unlucky draw of that distribution, not a regression.
- **Same class as V0's W-7** (`test_idempotency_is_scoped_per_agent_not_shared`, 5.4 %/run, fixed in V0.1 by
  giving the two agents fixed, unrelated names). This test file was **not touched by V7.5**.
- **Re-runs:** modified tree, in isolation: **3/3 passed**. `git stash -u` (tree = `d7d0369`, registry back to
  `("HTTP_AGENT_REGISTRY",)`), in isolation: **5/5 passed**; stash popped, tree verified identical.
- **Not fixed** (outside V7.5's diff scope; the brief says leave it). **Proposal recorded:** give the two
  `_register_agent` calls in that test fixed, dissimilar name/description/purpose (the V0.1 W-7 pattern) so the
  weighted score is a constant well below 0.72 — a test-data change only.

## Frontend + build

**384 passed (52 files)**; `tsc -b` clean (the `build-integrity` test typechecks the whole frontend);
`vite build` green. No frontend file changed. (`evidence/frontend_tests_and_build.txt`.)

## The scoped product diff (the exception, auditable)

`git diff --stat d7d0369 -- backend/app` + new files:

| path | kind | what |
|---|---|---|
| `backend/app/discovery/adapters/aws_bedrock_agents.py` | **new** | the adapter — the only new product module |
| `backend/app/discovery/adapters/registry.py` | modified | `+1` import (`aws_bedrock_agents`) in `_ensure_reference_adapter_registered`; docstring |
| `backend/app/discovery/adapters/__init__.py` | modified | docstring only |

Nothing else under `backend/app`; nothing under `frontend/`, `backend/migrations`, `backend/requirements*`, `lab/`,
`.github/`. Full patch: `evidence/product_diff_backend_app.patch`.

Tests (`evidence/test_diff_backend_tests.patch`): `backend/tests/discovery/test_aws_bedrock_agents_adapter.py`
(**new**, 33 items); `backend/tests/discovery/test_discovery_framework.py` — `test_ac15` tuple updated to the new
exhaustive registry `("AWS_BEDROCK_AGENTS", "HTTP_AGENT_REGISTRY")` + docstring (intent-preserving: still "the
registry is exhaustive and not a catalog"; `AZURE_AI_FOUNDRY`, `GCP_VERTEX_AGENTS`, `LANGGRAPH`, `CREWAI`,
`KUBERNETES`, `MCP` still banned).

Docs/tracking: `docs/architecture/adr/0024-…md` (new) + index row; `docs/discovery/framework.md` (reference-vs-
vendor section); `docs/validation/v7.5/**` (new); one paragraph each in `ROADMAP.md` and `REPO_STATE.md`.

## Migration

None. `alembic current` = `0061_assurance_evidence (head)` before and after; asserted by
`test_structural_no_migration_no_table_no_route_was_added`.
