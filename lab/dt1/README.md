# DT1 — Digital Twin, Stage 1 (canonical estate generator, contract, validator)

Stage 1 builds a **synthetic, deterministic, hash-sealed enterprise agent estate** and records its objective truth.
It never runs ACT against the estate, never produces ACT findings, never instantiates a process or service, and
never touches `backend/app`, `backend/migrations`, `backend/tests`, `frontend` or `.github` (the validator and the
boundary tests enforce this against `BASE_COMMIT`). Records live in `docs/dt1/`.

```
lab/dt1/
  grounding.py      # read-only AST + Base.metadata scan of the live model -> artifacts/schema_grounding.json, docs/dt1/SCHEMA_GROUNDING.md
  dt1_versions.py   # DT1_CANONICAL_SEED, GENERATOR_VERSION, schema/contract/matrix versions
  canonical.py      # canonical JSON bytes, sha256, stable ids <kind>-<20 hex of sha256(seed|kind|natural_key)>
  estate.py         # specification tables + build_estate(): derives conditions, reality classes, reachability
  contract.py       # build_contract(): OBSERVE / PARTIALLY_OBSERVE / NOT_OBSERVE / ENFORCE / REFUSE, grounded code refs
  matrix.py         # build_matrix() + render_markdown()
  seal.py           # anchor.json (hashes, root, seed, versions, git/base commit, created_at) + verify()
  validator.py      # 65 named checks over the artifacts (schema, vocab, legality, references, tenancy, control group,
                    # adversarial presence, no expectations/secrets/PHI, contract, matrix, canonical bytes,
                    # regeneration determinism, seal, empty production diff)
  cli.py            # generate | seal | validate | determinism | render
  tests/            # 30 pytest tests: positive+determinism (7), negative mutations (16), boundaries (7)
  artifacts/        # estate_truth.json, observability_contract.json, agent_property_matrix.json, anchor.json, schema_grounding.json
  BASE_COMMIT       # the commit the empty-production-diff guard compares against
```

Run (backend venv, no database needed except for `grounding.py`'s metadata scan, which needs only imports):

```
backend/.venv/Scripts/python lab/dt1/cli.py validate
backend/.venv/Scripts/python lab/dt1/cli.py determinism --runs 3
backend/.venv/Scripts/python -m pytest lab/dt1/tests -q
```

Re-grounding (`backend/.venv/Scripts/python lab/dt1/grounding.py`) after a product change changes
`schema_grounding_version` and therefore every sealed hash — by design. Seed: `dt1-canonical-v2-2026`.
