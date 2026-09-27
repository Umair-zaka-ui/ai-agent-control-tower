# DT1 Stage 1 — Determinism and the seal

## Inputs to determinism

| input | value |
|---|---|
| `DT1_CANONICAL_SEED` (the approved fixed demo seed) | `dt1-canonical-v2-2026` |
| `GENERATOR_VERSION` | `2.0.0` |
| `schema_grounding_version` (SHA-256 of the canonical grounding JSON) | `bee4a00b55c813209ca3d59d01734a2117caed92f7a527916070eecdf53409c3` |
| `estate_truth_schema_version` / `observability_contract_version` / `agent_property_matrix_version` | `1.0.0` / `1.0.0` / `1.0.0` |

Same seed + same generator version + same grounding ⇒ byte-identical artifacts ⇒ identical content hashes. A different
seed changes every identifier and therefore every hash while preserving the estate's *shape* (controlled variation); the
canonical demo always uses the fixed seed.

## How determinism is achieved

- **Canonical serialization** (`canonical.canonical_bytes`): UTF-8 JSON, `sort_keys=True`, separators `(",", ":")`,
  `ensure_ascii=False`, `allow_nan=False`, `\n` line ending, trailing newline. Every entity list is sorted by its stable id
  before serialization (`sort_entities`); nested lists of ids are sorted.
- **Stable identifiers**: `<kind>-` + first 20 hex characters of `SHA-256(seed | kind | natural_key)`; UUID-shaped
  companions (`act_*_uuid`) derived the same way for fields that are UUID-typed in ACT. No `uuid4`, no wall-clock, no
  environment path, no database-generated id, no unordered iteration.
- **Derived, not typed**: estate conditions, reality classes, sensitive-reach paths, the property matrix and the
  observability contract are all computed from the specification tables and the grounding JSON.
- The generator asserts the grounded vocabularies it depends on (`estate._check_vocab`) and exits with
  `GROUNDING CONFLICT` if the live model drifted — it never seals a guessed schema.

## Content hashes (sealed 2026-09-27T19:09:19+00:00)

| artifact | SHA-256 |
|---|---|
| `estate_truth.json` | `888eb44160dd40c271df2a7b2a2ca6c1931928c68661340f88b6eda36fb5c691` |
| `observability_contract.json` | `caa7db49ce5cb74e70284639c9a6632802e5b0ac050c87670a6d3d1aa19e78f9` |
| `agent_property_matrix.json` | `115574630f6a29df9e0eb662636c209f75311a3bc32cf9dc824890b52d747287` |
| **`combined_root`** = SHA-256(truth‖contract‖matrix hex digests, in that order) | `e06a07532d48c9d9e4681d827ea5ec8b1bece9909e4fd5e84db14f1fbbdebf5a` |

The **anchor record** (`lab/dt1/artifacts/anchor.json`) carries the seed, versions, `git_commit` at sealing
(`ab27fe3a70e72bc3981e9b63afe36eacd5ce90c7`), `base_commit` (the same — the branch point), the four hashes, the root order,
and `created_at`. **The anchor is not part of any hashed content**; `created_at` records *when the already-computed
hashes were sealed*. No artifact contains a timestamp, a path, or a hash of itself (the validator checks
`seal.anchor_not_in_content`). Stage 2 will verify this anchor predates ACT's first DT1 execution.

## Reproduce and verify

```
backend/.venv/Scripts/python lab/dt1/cli.py determinism --runs 3     # 3 regenerations byte-identical + different-seed control
backend/.venv/Scripts/python lab/dt1/cli.py validate                 # 65 checks incl. seal.hashes_match_anchor and determinism.regenerate_*
sha256sum lab/dt1/artifacts/estate_truth.json lab/dt1/artifacts/observability_contract.json lab/dt1/artifacts/agent_property_matrix.json
```

`cli.py generate --out <dir>` regenerates into another directory without touching the sealed artifacts; if
`schema_grounding.json` changes (a re-grounding after a product change), `schema_grounding_version` changes and so does
every hash — by design.
