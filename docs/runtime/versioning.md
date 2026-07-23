# Versioning

`/runtime/agents/{id}` (Versions section) · `runtime.version.*` permissions.

> **Phase 5.2 Part 1 note**: this doc originally described Phase 5.0's basic
> immutable-version mechanism (checksums, a 7-state lifecycle, unvalidated
> semantic versions). It has been extended in place — rather than forked
> into a second document — with the Enterprise Versioning & Release
> Management foundation: enforced semantic versioning, release channels, the
> snapshot builder, version lineage, release metadata/artifacts/notes, and
> the status-history ledger. Compatibility *analysis* and real cryptographic
> signing were out of scope for that part — the storage foundation for both
> existed (`compatibility_level`, `signature_id`) but nothing computed or
> verified them yet.
>
> **Phase 5.2.6 update**: compatibility analysis is no longer deferred — see
> "Compatibility & breaking-change detection" below.
>
> **Phase 5.2.4 update**: real cryptographic signing, provenance and
> portable attestation are no longer foundation-only either — see
> "Cryptographic signing, provenance & attestation" below. This phase also
> required a canonical-serialization refactor of the checksum routines
> themselves (see "Canonical serialization" below) — the one place in this
> phase's governing principle where shipped Part 1/5.2.6 behavior changed,
> deliberately and by design.

## Immutability & checksums (§11, §12)

An `agent_versions` row snapshots everything an execution needs: model
configuration, prompt, capability/tool references, and a policy snapshot —
so a running deployment is never affected by later edits to the agent's
definition. `checksum` is `sha256` of the canonical (sorted-key) JSON of
`{configuration_snapshot, prompt_snapshot, model_configuration,
capabilities_snapshot, tools_snapshot, policy_snapshot}`
(`app/runtime/services.py::_checksum`).

`AgentVersionService.publish()` recomputes the checksum and compares it to
the stored one before allowing `APPROVED → PUBLISHED`; a mismatch raises
`AGENT_VERSION_IMMUTABLE`. This is the tamper check §78 requires ("checksums
must detect tampering") — see `test_published_version_tamper_is_detected`.

## Lifecycle (§11, Phase 5.2 Part 1 §19-25)

```
DRAFT → READY_FOR_REVIEW → APPROVED → PUBLISHED → DEPRECATED → RETIRED
                                              └──→ REVOKED
```

(This environment's `validate()` goes straight to `READY_FOR_REVIEW`
synchronously — same simplification as the agent lifecycle; see
[agent-lifecycle.md](agent-lifecycle.md). The SRS 5.2 diagram names two
finer-grained gates, "Ready" and "Approval Required", between validation
and approval — deliberately kept as the single `READY_FOR_REVIEW` state
already in production use rather than split, to avoid a wide, purely
nominal rename across ~10 already-tested call sites for no behavioral
gain; see "What's deliberately not done" below.)

- **DRAFT** — editable. `configuration_schema`, capability/tool references
  and `model_configuration` can all still change (by creating the version
  fresh; there is no in-place PATCH on a version — see below). Release
  metadata, artifacts and release notes can be attached (§26-28, below).
- **READY_FOR_REVIEW** — `validate()` checked `model_configuration.provider`
  is present and the checksum still matches.
- **APPROVED** — a human approved it; `reviewed_by` is set to the approver.
- **PUBLISHED** — immutable from here on. `published_at` is set, the
  snapshot is built and frozen (§10-14, below), and release
  metadata/artifacts/notes can no longer be added. Only a published (or
  later-deprecated) version can be deployed (`AGENT_VERSION_NOT_PUBLISHED`
  otherwise).
- **DEPRECATED** — still executable (existing deployments keep working,
  §10.7 applies the same idea to agents), but new deployments should move
  off it. The only state `retire` is reachable from.
- **RETIRED** *(Phase 5.2 Part 1, §24-25)* — historical only; terminal.
  Cannot be deployed or rolled back to. `retired_at` is set.
- **REVOKED** — terminal, emergency stop. `AGENT_VERSION_REVOKED` blocks new
  executions immediately, from any prior state except RETIRED (there is no
  Retired → Revoked edge, matching the SRS diagram — a version already
  filed away as historical doesn't need an emergency stop). Accepts an
  optional `reason`, stored as `revoked_reason`.

There is intentionally no version-edit endpoint: creating a new version is
the only way to change behavior, which is what "immutable" means in
practice. `POST /agents/{id}/versions` auto-increments `version` per agent
(`1, 2, 3, …`) — the platform's internal release number.

## Semantic versioning (Phase 5.2 Part 1 §15-16)

Unlike Phase 5.0 (which accepted any string, unvalidated), `semantic_version`
is now enforced by `SemanticVersionService`
(`app/runtime/versioning/semantic_version.py`):

- Omit it and the platform auto-derives one: `0.1.0` for an agent's first
  version, otherwise the previous highest version's patch digit bumped by
  one (`0.1.0 → 0.1.1 → 0.1.2 …`).
- Supply one and it must be a valid `MAJOR.MINOR.PATCH` triple
  (`AGENT_VERSION_INVALID_SEMVER` otherwise), strictly greater than every
  other version already recorded for the agent, and not a duplicate
  (`AGENT_VERSION_SEMVER_NOT_INCREASING` otherwise). "Cannot skip existing
  versions" (SRS §16) is read as "no duplicates, no re-use" — jumping
  several MAJOR/MINOR numbers at once is normal, intentional SemVer usage
  and is not blocked.

## Release channels (Phase 5.2 Part 1 §9, §26)

A global catalog (`agent_release_channels`, seeded by migration `0025` with
`STABLE`/`BETA`/`CANARY`/`INTERNAL`) — `GET /release-channels` lists it.
Every version gets one at creation (`release_channel` in the create
payload, by name; defaults to the catalog's default, `STABLE`).

**Deliberately not enforced as a hard "one active release" gate**: the SRS
(§30) frames "cannot publish two active releases" as a rule, but this
platform's rollback and canary/blue-green deployment *strategies* (§15,
§57 — already shipped in Phase 5.0, see
[deployments.md](deployments.md)) require multiple versions of the same
agent to be simultaneously `PUBLISHED`; a `Deployment`, not a `Version`'s
status, tracks which one is live in a given environment. Blocking a second
publish on the same channel would break `test_deployment_rollback`'s
exact, already-production scenario. Supersession is still tracked
informationally: publishing a new version sets the immediately-preceding
version's `superseded_by_id` if that predecessor has already been
deprecated (see Lineage, below) — so "what replaced what" always has an
answer without blocking legitimate multi-version deployment topologies.

## Snapshot builder (Phase 5.2 Part 1 §10-14)

`SnapshotBuilderService` (`app/runtime/versioning/snapshot.py`) builds one
frozen document — registry identity, technical definition, runtime
configuration, and everything attached under release management (metadata,
artifacts, notes) — and stores it in `agent_version_snapshots`, exactly
once, at `publish()`. `GET /agents/{id}/versions/{versionId}/snapshot`
returns it (`null` before publish). `agent_versions.snapshot_reference` is
set to `snapshot:<id>` at the same time.

Publish time (not creation time) is the freeze point deliberately: it's the
true immutability boundary (§21, "Published Version: Immutable."), and it
lets release metadata/artifacts/notes be attached any time before publish
— see below — without needing to rebuild an earlier snapshot.

Per §12 ("a snapshot must never reference mutable records... copy values"),
every field in the document is copied by value at build time, never a
lazily-resolved foreign key.

## Version lineage (Phase 5.2 Part 1 §17-18)

`VersionLineageService` (`app/runtime/versioning/lineage.py`) maintains
three pointers directly on `agent_versions` (index/bookkeeping metadata,
not part of the frozen snapshot — updating them doesn't violate §14's
snapshot-immutability rule):

- **`parent_version_id`** — set at creation, to the agent's latest existing
  version at that moment.
- **`superseded_by_id`** — set on the *previous* version when a new one
  publishes, if that previous version has already been deprecated (see
  "Release channels" above for why this isn't a hard block).
- **`rollback_target_id`** — set explicitly via
  `POST .../versions/{id}/rollback-target`; the target must be another
  version of the same agent, not itself, and `PUBLISHED` or `DEPRECATED`
  (`AGENT_VERSION_ROLLBACK_TARGET_INVALID` otherwise). Setting the pointer
  is foundation-only in this part — actually executing a rollback is
  deferred (see below); `DeploymentService`'s existing
  `POST /deployments/{id}/rollback` (Phase 5.0) is unrelated and still the
  only thing that changes what's actually running.

## Release metadata, artifacts and release notes (Phase 5.2 Part 1 §26-28)

Three satellite tables, one service each
(`app/runtime/versioning/{release_metadata,artifacts,notes}.py`), all
gated by the same immutability rule (`ensure_not_locked` in
`app/runtime/versioning/locking.py`): attachable while a version is DRAFT
through APPROVED; frozen forever once PUBLISHED (`AGENT_VERSION_SNAPSHOT_
LOCKED` on any further attempt).

- **Release metadata** (`agent_release_metadata`, one row per version) —
  release name/description, business justification, change category
  (MAJOR/MINOR/PATCH/HOTFIX), release window, support end date, approval
  ticket, source branch, commit/build references, risk score, docs URL.
  `GET`/`POST .../versions/{id}/release-metadata` (POST upserts).
- **Release artifacts** (`agent_release_artifacts`, many per version) —
  reference-only (never a binary): `OCI_IMAGE_DIGEST`, `GIT_COMMIT_SHA`,
  `BUILD_PIPELINE_ID`, `MODEL_PACKAGE`, `PROMPT_PACKAGE`, `CONFIG_BUNDLE`,
  `SBOM_REFERENCE`, `SIGNATURE_REFERENCE`. `GET`/`POST
  .../versions/{id}/artifacts`.
- **Release notes** (`agent_release_notes`, many per version) —
  categorized (`ADDED`/`CHANGED`/`FIXED`/`REMOVED`/`SECURITY`/`DEPRECATED`)
  free-text entries, distinct from the pre-existing
  `agent_versions.release_notes` single free-text summary field (kept
  as-is). `GET`/`POST .../versions/{id}/notes`.

All three are copied into the frozen snapshot document at publish time
(above), so whatever was attached before publish is what the permanent
record shows.

## Status history (Phase 5.2 Part 1 §19, §25)

`agent_version_status_history` — one row per transition, including the
initial `None → DRAFT` at creation, mirroring `AgentLifecycleEvent` for the
Phase 5.1 registry. `GET /agents/{id}/versions/{versionId}/status-history`.

## Version comparison (Phase 5.2 Part 1 §3)

`VersionComparisonService` (`app/runtime/versioning/compare.py`) — a
read-only structural diff between two versions of the same agent, via
`GET /agents/{id}/versions/{versionId}/compare/{otherVersionId}`. Scalar
fields (`semantic_version`, `status`, `release_branch`, `release_notes`,
release channel name, release name) are compared directly; JSONB
configuration fields (`configuration_snapshot`, `model_configuration`,
`policy_snapshot`) get a key-level added/removed/changed breakdown;
list-shaped snapshots (`capabilities_snapshot`, `tools_snapshot`) are
compared as sets; artifacts and notes are compared by (type, reference) /
(category, note) tuples. Works regardless of either version's lifecycle
status — comparing a DRAFT against a PUBLISHED version is a normal "preview
what this change would alter" use case. The URL scopes both versions to
one agent, so a version belonging to a different agent 404s rather than
producing a cross-agent diff.

## Promotion readiness (Phase 5.2 Part 1 §3, §30; Phase 5.2.6)

`VersionReadinessService` (`app/runtime/versioning/readiness.py`) — a
read-only diagnostic, `GET /agents/{id}/versions/{versionId}/readiness`,
that evaluates §30's "Version Readiness" checklist and reports which
conditions are and aren't met. It never blocks or gates anything itself
(the actual lifecycle actions have their own, separate checks) — it's
purely advisory, e.g. for a release-management dashboard. Checks:
`snapshot_creation` (a dry-run build, never persisted), `validation_passed`
(the same checks `validate()` runs), `metadata_complete`, `owners_assigned`,
`registry_active`, `no_blocking_governance_findings` (reuses the Phase 5.1
registry validation engine's latest run for the agent), `artifacts_present`,
`compatibility_analysis` (Phase 5.2.6 — see below; no longer `skipped: true`),
and `approval_prerequisites_satisfied`.

## Compatibility & breaking-change detection (Phase 5.2.6, ACT-VER-FR-100..108)

`CompatibilityAnalysisService` (`app/runtime/versioning/compatibility.py`)
classifies a candidate version against a resolved baseline into
`COMPATIBLE` / `BACKWARD_COMPATIBLE` / `BREAKING` / `UNKNOWN`, stores the
verdict on `agent_versions.compatibility_level` (reserved but dead since
Part 1) plus the two columns this phase adds —
`compatibility_baseline_id`, `compatibility_analyzed_at` — and records one
`agent_version_compatibility_findings` row per detected change.

**Trigger**: automatic, as a best-effort follow-up right after `publish()`'s
own commit succeeds — a bug in the analyzer is logged and swallowed, never
blocking publication (see "Advisory, not enforcement" below). Also available
on demand via `POST .../compatibility/analyze` (recomputes and persists; the
only way to backfill a version published before this phase existed).

**Baseline resolution** (`resolve_baseline`), in order:

1. An explicit `?baseline_version_id=` override, if supplied — validated to
   belong to the same agent (`COMPATIBILITY_BASELINE_NOT_FOUND` otherwise).
2. `parent_version_id` (set at creation — see "Version lineage" above),
   regardless of that parent's lifecycle status.
3. The highest-`version` `PUBLISHED` version of the same agent older than
   the candidate.
4. None of the above → `UNKNOWN`, with one explanatory finding — this is the
   correct, expected result for an agent's first version, not an error.

**Classification rules** (`classify_change` and its `compare_*` helpers) —
one breaking finding makes the whole version `BREAKING` regardless of how
many compatible/backward-compatible findings accompany it:

| Category | BREAKING | BACKWARD_COMPATIBLE | COMPATIBLE |
|---|---|---|---|
| `INPUT_CONTRACT` | field removed; type narrowed; required field added with no default; optional → required | optional field added (with or without a default); type widened; required → optional | — |
| `OUTPUT_CONTRACT` | field removed | field added; type widened | — |
| `TOOL_BINDING` / `CAPABILITY` | entry removed | entry added | — |
| `MODEL_CONFIG` | `provider`/`model` changed | — | sampling parameters (`temperature`, `top_p`, `top_k`, penalties) changed — behavioral drift, not a contract break; anything else unrecognized |
| `RESOURCE_LIMIT` | numeric value reduced | numeric value increased | — |
| `POLICY` | `approved_models` narrowed or introduced; an environment added to `prohibited_environments`/`requires_approval_environments` | `approved_models` widened or removed; an environment removed from either list | — |
| `PROMPT` / `METADATA` | — | — | prompt content, release notes always compatible |

Three data-source decisions, made explicit in `compatibility.py`'s module
docstring since a wrong guess here would propagate into every future
compatibility judgment:

- **Input/output contract** reads `AgentDefinition.input_schema`/
  `output_schema` (real JSON Schema, already used elsewhere in this codebase
  to validate execution payloads) — not `AgentVersion.configuration_snapshot`,
  which today is simply a copy of `model_configuration` with no "inputs"
  substructure of its own.
- **Resource limits** have no dedicated field anywhere in a version or its
  snapshot (`AgentDeployment.runtime_limits` is per-environment, not
  per-version, and isn't part of what a version snapshots). This module
  scans `model_configuration` for numeric values whose key name looks like a
  limit/quota (`max_*`/`*_limit`/`*_timeout`/`*_quota`/`*_cap`) — a
  heuristic, excluding the sampling parameters below.
- **Policy tightening** is scored only for the three `policy_snapshot` keys
  `RuntimePolicyService.evaluate` (`app/runtime/services.py`) actually gives
  meaning to (`approved_models`, `prohibited_environments`,
  `requires_approval_environments`), not guessed at for arbitrary future keys.

Like `VersionComparisonService` and `VersionReadinessService`, this reads
directly from `AgentVersion`/`AgentDefinition` ORM columns, not the frozen
`agent_version_snapshots.snapshot` document — those columns are exactly what
the frozen document is built from, and reading them directly lets a
still-DRAFT version be analyzed (e.g. via the readiness check) before
anything has ever been published.

**Semver consistency** — the declared `semantic_version` increment (major/
minor/patch, computed from the same `parse_semver` Part 1 already ships) is
compared against the detected level's expected minimum (`BREAKING` → major,
`BACKWARD_COMPATIBLE` → minor, `COMPATIBLE` → patch; a larger declared bump
always satisfies a smaller expectation).

**Advisory, not enforcement — a deliberate SRS deviation.** The SRS frames a
semver/compatibility mismatch as something publication should reject. This
implementation does not: Part 1 already established that comparison and
readiness never gate a lifecycle action (see "Promotion readiness" above and
`docs/runtime/versioning.md`'s Part 1 history), and reversing that here for
one specific check would be inconsistent and would break the existing
publish-focused tests that assume `publish()` only checks status +
checksum. Instead, an inconsistency is **reported**: as a
`semver_consistent: false` field on the compatibility report, and as a
failed (not blocking) `compatibility_analysis` readiness check. A correctly
major-bumped `BREAKING` version reports as a passing-but-cautionary check
(the message says so explicitly); only a genuine inconsistency fails the
check — and even then, nothing stops `validate()`/`approve()`/`publish()`
from proceeding.

**API**: `GET .../versions/{id}/compatibility` (last-persisted report, or an
ephemeral evaluation against an explicit `?baseline_version_id=` override —
never persisted in that case), `POST .../versions/{id}/compatibility/analyze`
(always recomputes and persists), `GET .../versions/{id}/compatibility/findings`
(the persisted findings list). All three reuse `runtime.version.view` — no
new permission was needed.

## Canonical serialization (Phase 5.2.4, ACT-VER-FR-025, FR-040..FR-047)

`app/runtime/versioning/canonical.py` is the single source of truth for
turning a Python object into the exact bytes that get hashed and signed.
Before this phase, `_checksum()` (`services.py`) and `checksum_of()`
(`snapshot.py`) both hashed `json.dumps(..., sort_keys=True, default=str)`
output — correct as long as the same process wrote and verified, but not a
stable, cross-language contract: Python's `json.dumps` defaults for
Unicode representation and (via `default=str`) arbitrary-type stringification
aren't specified anywhere a second implementation could reproduce them. A
signature over a non-reproducible digest is worthless — the moment an
external auditor, or a second implementation in another language,
recomputes the digest with different serialization, verification fails on
an artifact that was never tampered with, and the failure is silent and
looks like tampering.

**The rules** (a second-language implementation must reproduce every one):

| Rule | Specification |
|---|---|
| Key ordering | Lexicographic by Unicode code point, recursively, at every depth |
| Unicode normalization | NFC, applied to every string key and value |
| Encoding | UTF-8, no BOM |
| Whitespace | None — `,` and `:` separators exactly |
| Non-ASCII | Emitted literally, never `\uXXXX`-escaped |
| Floats | Rejected — `CanonicalizationError`. See below. |
| Integers | No leading zeros or `+` (already true of every Python `int`) |
| Booleans / null | `true` / `false` / `null` |
| Nested containers | Every rule above applies recursively; list order is preserved (only object keys sort) |

`digest(obj)` returns `sha256:<64 lowercase hex>` — algorithm-prefixed
(`ACT-VER-FR-041`) so a future second algorithm is a different prefix, not a
format migration.

**The float decision**: IEEE-754 floats do not round-trip reliably across
JSON encoders/languages (`0.1 + 0.2` serializes differently in Python, Go,
and JavaScript), so `canonicalize()`/`digest()` raise
`CanonicalizationError` the instant one appears anywhere in the structure —
they never silently guess a portable representation. `stringify_floats()`
is the documented, explicit, opt-in conversion producers use instead.
**Finding, as required by this phase**: `model_configuration.temperature`/
`top_p` are exactly the float fields this codebase actually produces (see
the compatibility-detection sampling-parameter list in the section above);
`_checksum()` and `checksum_of()` both call `stringify_floats()` on their
input before digesting.

**Known-answer vectors** (also committed as `KNOWN_ANSWER_VECTORS` in
`backend/tests/runtime/test_canonical.py`, so a second implementation can
check its own output against the same fixed inputs):

| Input | `digest()` |
|---|---|
| `{}` | `sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a` |
| `[]` | `sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| `None` | `sha256:74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b` |
| `{"a": 1, "b": "two", "c": True, "d": None}` | `sha256:eb2c149467b56cfad324e3c07e2eb850f0481017871fe2250e3d21c9d0ba1fdc` |
| `{"outer": {"z": 1, "a": [3, 2, 1]}, "flag": False}` | `sha256:f9de48f91c5f237ea969b03b9d8c8dabf4bf81d9353800ce3840afcb2167e49a` |
| `{"name": "héllo wörld 🎉"}` | `sha256:3af931f0fc2a91cbcfcd909e0d2b0962c43b0a7a1cdef759a8767d16392508c1` |

**Migrating existing rows**: `agent_versions.checksum_algorithm` and
`agent_version_snapshots.checksum_algorithm` (migration `0027`) default to
`'legacy-sha256'` for every row that existed before this migration ran; new
rows set `'canonical-sha256'` explicitly at creation (`AgentVersionService.
create`, `SnapshotBuilderService.build_and_store`). Verification branches
on the column (`_verify_checksum` in `services.py`) — legacy rows verify
against `_legacy_checksum`/`_legacy_checksum_of` (the original, unchanged
routines, kept and clearly marked deprecated), canonical rows against the
new `canonical.digest()`-backed ones. **The migration itself never
recomputes a single existing checksum** — silently rewriting integrity
values in a schema migration, with no audit trail of who ran it or when,
is precisely what this phase exists to prevent. `backend/scripts/
recompute_checksums.py` is the explicit, operator-invoked, audited
alternative (`--dry-run` reports without writing).

Both checksum columns were also widened from 64 to 80 characters to fit the
new algorithm-prefixed format (`"sha256:<64 hex>"` is 71 characters);
legacy bare-hex values fit unchanged. Two pre-existing tests that asserted
the legacy bare-64-hex length (`test_snapshot_is_built_only_at_publish`,
`test_version_lifecycle_and_checksum`) were updated to assert the new
format instead — the only tests this phase touched, per its own governing
principle's one authorized exception.

**A second bug the refactor surfaced**: `build_snapshot()` (`snapshot.py`)
previously embedded `release_metadata.release_window_start`/
`release_window_end`/`support_end_date` as raw `datetime` objects, relying
on the old `checksum_of()`'s `default=str` to paper over it with Python's
non-portable `str(datetime)` formatting. `canonical.py` refuses to guess a
representation for an unsupported type, so this had to be fixed as a
precondition for the refactor: those three fields are now `.isoformat()`
strings in the snapshot document, matching the `created_time` field right
next to them, which already did this correctly.

## Cryptographic signing, provenance & attestation (Phase 5.2.4, ACT-VER-FR-060..071)

Every `publish()` now produces a cryptographic signature over the frozen
snapshot, plus a portable, self-contained attestation document describing
exactly what was published and by whom.

### Signing provider abstraction

`app/runtime/versioning/signing/` — `SigningProvider` (`base.py`) is the
interface; `LocalKeyProvider` (`local.py`, Ed25519 via the `cryptography`
library) is the only implementation today; `registry.py` selects one from
`settings.SIGNING_PROVIDER`, so swapping to Azure Key Vault at deployment
is a configuration change, not a rewrite. **Private key material never
crosses the interface**: `sign()` takes bytes and returns a signature,
never a key; nothing outside `local.py` reads a key file.

Local keys live at `settings.SIGNING_KEY_PATH` (default `./.keys/`,
gitignored), one PEM pair per key version
(`{key_id}.v{n}.pem`/`{key_id}.v{n}.pub.pem`). A keypair is auto-generated
on first use if absent, logging a clear warning that it is not
production-grade. `SigningKeyService` (`keys.py`) is the database record of
a key's *public* material and lifecycle (`signing_keys`/
`signing_key_versions`) — it never touches private key material itself,
only calling into the provider for cryptographic operations.

### Signing at publish time

Order, inside `AgentVersionService.publish()` (`services.py`), after the
snapshot is built and frozen:

1. Compute the snapshot's canonical digest (already done by
   `SnapshotBuilderService`).
2. Compute the **manifest digest** — a canonical digest over
   `{schema_version, snapshot_digest, agent_id, version_id,
   semantic_version, version_number, published_at}`
   (`compute_manifest_digest`) — a small, unambiguous object identifying
   *this exact publish*, not the snapshot body again.
3. Build the attestation document (below).
4. Sign the DSSE Pre-Authentication Encoding of that document via the
   provider, wrap the result in a DSSE envelope.
5. Persist an `agent_version_signatures` row (`signature_type='PUBLISHER'`)
   and an `agent_version_provenance` row.
6. Set `agent_versions.manifest_digest`/`signed_at`.

**Fail-closed — the opposite policy from Phase 5.2.6's compatibility
analysis.** Compatibility analysis is advisory: a bug in it is logged and
swallowed after `publish()`'s own commit, so it can never make a version
unpublishable. Signing is not advisory — `ACT-VER-NFR-004` requires
fail-closed, since an unsigned published version is an integrity hole. The
signing call in `publish()` is deliberately **not** wrapped in `try`/
`except`: it runs *before* the transaction commits, so an exception there
propagates out of `publish()` entirely, the session's pending changes are
discarded when the request's `get_db` dependency closes it, and the
version never reaches `PUBLISHED`.

`agent_versions.signature_id` (added by Part 1, always null until now) is
wired to this primary `PUBLISHER` signature's id, rather than dropped —
the column's own name already says "the id of *the* signature," which maps
naturally onto "the primary one," the same way `snapshot_reference` already
denormalizes a pointer onto the version row.

### Key rotation and revocation

`POST /signing-keys/{key_id}/rotate` generates a new key version (the
previous version's public key stays retrievable — old signatures must stay
verifiable) and makes it current; `POST /signing-keys/{key_id}/revoke`
marks the key `REVOKED` and sets every affected signature's
`verification_status` to `'KEY_REVOKED'` **without altering the version
record or the signature bytes themselves** (`ACT-VER-FR-066`) — the
historical fact that it was signed remains true, only its current trust
status changes. Both operate only on a key that already has a database
row — an unrecognized `key_id` 404s (`SIGNING_KEY_NOT_FOUND`) rather than
being silently auto-provisioned, which only the internal first-use path
(`ensure_key`, called from `publish()`/`countersign()`) does.

### Key rotation & revocation runbook

**Routine rotation** (no suspected compromise — e.g. a periodic policy):

1. `POST /api/v1/runtime/signing-keys/{key_id}/rotate` (requires
   `runtime.signing.manage`). The previous version keeps signing history
   verifiable — nothing needs re-signing.
2. New `publish()`/`countersign()` calls automatically use the new current
   version from this point on; no other action needed.

**Suspected key compromise**:

1. `POST /api/v1/runtime/signing-keys/{key_id}/revoke` with a `reason` —
   immediately marks every signature made with that key
   `verification_status: 'KEY_REVOKED'` platform-wide. This does **not**
   unpublish anything or alter any version/signature row.
2. Rotation is blocked on a revoked key (`SIGNING_KEY_REVOKED`) — a
   revoked `key_id` is retired permanently; sign with a **different**
   `key_id` going forward (a new `key_id` is provisioned automatically the
   next time something signs with it).
3. Treat every version whose primary signature now shows
   `KEY_REVOKED` as needing manual review — `POST .../verify` on each
   still reports whether the *content* is intact, but the trust chain back
   to that key is broken.
4. There is currently exactly one operational key per deployment
   (`settings.SIGNING_DEFAULT_KEY_ID`, default `"default"`) — `signing_keys`
   has no per-organization scoping (a deliberate global-catalog choice, see
   "Release channels" above for the same pattern), so a revocation is
   platform-wide, not scoped to one tenant.

**Local-provider file loss** (`SIGNING_PROVIDER=LOCAL` only): if
`settings.SIGNING_KEY_PATH` is lost (e.g. a wiped dev environment), every
existing signature becomes unverifiable (`SIGNING_KEY_NOT_FOUND` on
verify) — there is no recovery path for a lost local private key by
design. This is a further reason Azure Key Vault, not more local-provider
tooling, is the intended production path (see Known Deviations).

### Portable attestation

`app/runtime/versioning/attestation.py` builds an in-toto Statement v1
document (`predicateType`:
`https://ai-agent-control-tower.io/AgentVersionAttestation/v1`) and wraps
it in a DSSE envelope (`application/vnd.in-toto+json`). Every predicate
field is copied by value at build time — the agent's actual name/slug, the
version's actual semantic version/status, digests, timestamps, opaque UUID
identifiers — never a foreign key that only resolves through this
platform's schema. `subject[0].digest.sha256` is bare hex (no `sha256:`
prefix), per in-toto's own convention, even though every digest elsewhere
in this codebase is prefixed.

The DSSE signature covers the **Pre-Authentication Encoding** (PAE) of the
payload, not the raw payload — `pae(payloadType, payload) = "DSSEv1" SP
LEN(payloadType) SP payloadType SP LEN(payload) SP payload`, per the DSSE
spec exactly. Signing the raw payload instead would silently break every
external verifier that follows the spec.

**Verification scope — internal only, deliberately.** This phase builds no
public endpoint and no standalone verifier script — `POST .../verify` is
authenticated and organization-scoped like every other route here
(`ACT-VER-FR-070`, the public verification endpoint, is deferred — see
Known Deviations). The in-toto/DSSE format is followed anyway: signed
artifacts accumulate, and the signature covers the document's *shape* —
changing that shape later means re-signing every version that already
exists, while following a documented external format now costs nothing and
keeps the door open. `POST .../verify` independently re-verifies every
signature row for a version (never trusting the persisted
`verification_status` alone) plus whether the frozen snapshot still
matches what was signed, so it catches both a tampered signature/payload
and a tampered snapshot as two orthogonal signals.

### Countersigning

`POST .../countersign` (`runtime.agent.approve` — see "Permission mapping"
below) adds an additional, independent signature over the *same* payload
the `PUBLISHER` signature covers (`ACT-VER-FR-069`: multiple signatures per
version permitted) — each signature row carries its own minimal envelope
(the shared payload plus just its own `signatures` entry), so every
signature verifies independently of every other one.

### API

`GET`/`POST .../versions/{id}/signatures`, `.../provenance`,
`.../attestation`, `.../verify`, `.../countersign`; `GET /signing-keys`,
`POST /signing-keys/{key_id}/rotate`, `POST /signing-keys/{key_id}/revoke`.
Two new permissions, `runtime.signing.view`/`runtime.signing.manage`, for
the signing-key endpoints; the version-scoped endpoints reuse
`runtime.version.view`.

**Permission mapping decision**: the countersign endpoint's obvious
permission — "whoever can approve a version" — already exists in this
codebase as `runtime.agent.approve` (the permission `approve_version`,
DRAFT→APPROVED, already uses), not a separate `runtime.version.approve`
code. Reusing it rather than inventing a same-meaning synonym matches this
phase's own instruction to add a new permission "only if you find a
concrete reason" — there isn't one here.

### Known Deviations

- **`ACT-VER-NFR-002`** ("private key material must never enter process
  memory") **is violated by the local file-based provider by
  construction** — signing necessarily reads the private key bytes from
  disk into this process's memory for the duration of the `sign()` call.
  Accepted pre-production; **closes when Azure Key Vault** (which signs
  server-side and never exposes key material to the calling process) lands
  as a second `SigningProvider`.
- **`ACT-VER-FR-070`** (a public, unauthenticated verification endpoint) is
  **deliberately deferred** — every route this phase adds requires
  authentication and organization scoping (see "Verification scope"
  above). **Closes** when external/public verification is actually needed;
  the attestation format was chosen specifically so that's a routing
  decision at that point, not a re-signing exercise.

## Capability/tool references on a version

`capability_ids`/`tool_ids` passed at version creation both (a) get
recorded in the immutable `capabilities_snapshot`/`tools_snapshot` JSON
arrays, and (b) create `agent_capabilities`/`agent_tools` assignment rows
scoped to that version (`status=REQUESTED`). This is separate from — and in
addition to — assigning a capability/tool directly to the agent (no
`agent_version_id`) from the agent detail page; see
[capabilities-and-tools.md](capabilities-and-tools.md).

## What's deferred

Actually executing a rollback, canary rollout, or traffic shift belongs to
deployments (Phase 5.0, already shipped) and future runtime work, not this
versioning foundation. Compatibility *analysis* (Phase 5.2.6) and
cryptographic signing/provenance/attestation (Phase 5.2.4) are no longer
deferred — see their sections above. Within signing itself, two things
remain deferred on purpose — see Phase 5.2.4's "Known Deviations": Azure
Key Vault as a second `SigningProvider` (closes `ACT-VER-NFR-002`), and a
public/unauthenticated verification endpoint (`ACT-VER-FR-070`).

## What's deliberately not done

Splitting `READY_FOR_REVIEW` into the SRS's separate "Ready" and "Approval
Required" states was considered and rejected for this part: it's a purely
nominal distinction with no new validation behavior attached to either
half, and renaming it would touch roughly ten already-tested files (routes,
services, tests, frontend types/badges) for no functional gain. If a real
"Ready" gate (e.g. an automated pre-approval check distinct from
`validate()`) is needed later, it can be inserted without disturbing the
existing state name.
