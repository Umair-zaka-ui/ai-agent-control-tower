# Permission caching (Phase 4.3.2 §10, §26)

Resolving an identity's grants touches roles, hierarchy and permissions — too much to
repeat on every request. The resolved grant list is cached per identity and invalidated
by a version bump. Postgres-backed (ADR-0002: no second datastore).

## How it works

- **`permission_versions`** holds one monotonic `version` per organization.
- **`permission_cache`** holds one row per identity: the resolved `grants_json`, the
  `version` it was built at, and an `expires_at` (TTL, `PERMISSION_CACHE_TTL_SECONDS`,
  default 300s).
- On `authorize`, `PermissionCacheService` reads the identity's cache row. It is a
  **hit** only if `row.version == current org version` **and** not expired; otherwise it
  rebuilds and upserts the row (`ON CONFLICT (identity_id) DO UPDATE`).

Cache key (§10): `organization_id` + `identity_id` + `version` (which folds in role +
permission + assignment changes).

## Invalidation (§26)

Any role / permission / assignment / hierarchy change **bumps the acting org's version**
(`_commit_invalidating` in the authorization routes). That immediately makes every cached
row for the org stale — no row-by-row deletion. Because system/global roles are
permission-protected, only org-scoped changes alter grants at runtime, so bumping the
acting org's version is sufficient and immediate.

## Safety

- The cache stores only what the engine resolved; it never changes a decision, only
  avoids recomputing it. A cache write failure is swallowed — the next call is simply a
  miss, never a wrong answer.
- Toggle with `PERMISSION_CACHE_ENABLED`. With it off, every check resolves directly.

## Performance intent (§25)

Targets: cold lookup <10ms, warm (cache hit) <2ms, middleware <5ms. The warm path is a
single indexed `permission_cache` read plus in-memory evaluation. These are **indexed
for** but not formally benchmarked here; the `/authorization/check` response includes
`evaluation_time_ms` and `cache_hit` for observability.
