# Versioning

`/runtime/agents/{id}` (Versions section) · `runtime.version.*` permissions.

> **Phase 5.2 Part 1 note**: this doc originally described Phase 5.0's basic
> immutable-version mechanism (checksums, a 7-state lifecycle, unvalidated
> semantic versions). It has been extended in place — rather than forked
> into a second document — with the Enterprise Versioning & Release
> Management foundation: enforced semantic versioning, release channels, the
> snapshot builder, version lineage, release metadata/artifacts/notes, and
> the status-history ledger. Compatibility *analysis* and real cryptographic
> signing are explicitly out of scope for this part (see "What's deferred"
> below) — the storage foundation for both exists (`compatibility_level`,
> `signature_id`) but nothing computes or verifies them yet.

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

## Promotion readiness (Phase 5.2 Part 1 §3, §30)

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
`compatibility_analysis` (always reported `skipped: true` — deferred to
Part 3, so it can never fail a check this part doesn't implement), and
`approval_prerequisites_satisfied`.

## Capability/tool references on a version

`capability_ids`/`tool_ids` passed at version creation both (a) get
recorded in the immutable `capabilities_snapshot`/`tools_snapshot` JSON
arrays, and (b) create `agent_capabilities`/`agent_tools` assignment rows
scoped to that version (`status=REQUESTED`). This is separate from — and in
addition to — assigning a capability/tool directly to the agent (no
`agent_version_id`) from the agent detail page; see
[capabilities-and-tools.md](capabilities-and-tools.md).

## What's deferred

Per the SRS's own scope boundary (§3, §30): compatibility *analysis*
(computing what `compatibility_level` should actually be) is explicitly
"implemented in Part 3" — this part only reserves the column. Real
cryptographic signing (verifying `signature_id`) is likewise foundation-only
— nothing generates or checks a signature yet. Actually executing a
rollback, canary rollout, or traffic shift belongs to deployments
(Phase 5.0, already shipped) and future runtime work, not this versioning
foundation.

## What's deliberately not done

Splitting `READY_FOR_REVIEW` into the SRS's separate "Ready" and "Approval
Required" states was considered and rejected for this part: it's a purely
nominal distinction with no new validation behavior attached to either
half, and renaming it would touch roughly ten already-tested files (routes,
services, tests, frontend types/badges) for no functional gain. If a real
"Ready" gate (e.g. an automated pre-approval check distinct from
`validate()`) is needed later, it can be inserted without disturbing the
existing state name.
