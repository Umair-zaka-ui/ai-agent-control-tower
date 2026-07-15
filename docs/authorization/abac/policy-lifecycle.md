# ABAC policy lifecycle (Phase 4.3.5 §7, §28)

```
DRAFT → VALIDATED → ACTIVE (published) → DISABLED / DEPRECATED / ARCHIVED
```

- **Drafts never affect decisions.** Only ACTIVE policies are resolved.
- `POST …/validate` runs the full §24 validation (schema, attributes,
  operators, types, effect, obligations, target, scope) and promotes a clean
  draft to VALIDATED. Publish re-validates — **compile-on-publish** (§28): an
  ACTIVE policy is guaranteed well-formed, so runtime never re-parses
  unvalidated JSON.
- **Published versions are immutable.** Editing an ACTIVE policy creates a new
  DRAFT version in the same family; publishing it deprecates the previous
  ACTIVE one — at most one ACTIVE version per family.
- Every publish snapshots the version to `abac_policy_versions`.
  **Rollback** (`POST …/rollback/{version}`) creates and publishes a new
  version from the chosen snapshot — history is never rewritten.
- `DELETE` works only on never-published drafts; anything published must be
  **archived** (`ABAC_POLICY_CONFLICT` otherwise, §40.13).
- Disable stops enforcement immediately (cache invalidated); archived policies
  remain readable for audit.

Every transition is audited: `ABAC_POLICY_CREATED / UPDATED / VALIDATED /
PUBLISHED / DISABLED / ARCHIVED / ROLLED_BACK` (§38).

## Caching (§27)

Active policy sets are cached per tenant in-process and version-invalidated on
any policy mutation. Volatile attributes (risk scores, time, device trust) are
never cached — they are collected per evaluation.

## Exceptions

`abac_policy_exceptions` grants one subject a time-boxed exemption from one
policy (optionally narrowed to one resource). Rules (§21, §40.12):

- requires `authorization.exception.manage` and an explicit `valid_until`;
- the resolver skips an excepted policy for that subject only;
- expiry is automatic — a lapsed exception is marked `EXPIRED` on first use
  and audited (`POLICY_EXCEPTION_EXPIRED`);
- creation and revocation are audited (`POLICY_EXCEPTION_CREATED`).
