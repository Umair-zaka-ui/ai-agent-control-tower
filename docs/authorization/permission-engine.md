# Permission Engine (Phase 4.3.2)

Every authorization decision in the platform flows through one **PermissionEngine**.
Controllers, services and the API never branch on role names — they ask the engine.

```python
# ❌ never
if user.role == "admin": ...
# ✅ always
Depends(require_permission("agent.delete"))   # gate
PermissionCacheService(db).authorize(user, "agent.delete", ctx)   # programmatic
```

## Pipeline (§6, §9)

```
identity → resolve roles (+ inherited) → collect grants (allow/deny)
        → expand wildcards → apply scope → resolve conflicts → ALLOW / DENY → audit
```

Each stage is a small, testable resolver in `app/authorization/engine.py`:

| Resolver | Job |
|----------|-----|
| `RoleResolver` | assigned roles + every descendant via `role_hierarchy` (§12) |
| `PermissionResolver` | build the full **grant list**: legacy fallback + each scoped assignment's role permissions | 
| `WildcardResolver` | `*` and `resource.*` matching (§13, §14) |
| `ScopeResolver` | does a grant apply to this request/resource? (§15) |
| `ConflictResolver` | **explicit deny > allow > default deny** (§16) |

A **grant** is `(pattern, effect, scope, source_role, scope-ids)`. Resolution (DB-heavy)
happens once and is cached; evaluation is pure and in-memory.

## Decision (§17)

`authorize()` returns:

```json
{ "allowed": true, "permission": "agent.execute",
  "reason": "Granted by ROLE_AI_OPERATOR", "scope": "DEPARTMENT",
  "source_role": "ROLE_AI_OPERATOR" }
```

Default is **deny** — a permission with no matching allow grant is refused.

## Integration

- **Gate**: `require_permission("code")` (`app/api/deps.py`) now routes through the
  cached engine, so inheritance, wildcards, scope and deny apply on *every* endpoint.
- **Endpoint**: `POST /api/v1/authorization/check` `{permission, resource_type?, resource_id?}`
  → `{allowed, reason, scope, source_role, evaluation_time_ms, cache_hit}` for the
  calling identity.
- **Frontend**: `useCan("agent.create")`, `<ProtectedComponent permission=…>` (§23, §24).

## Audit & events (§18, §27)

The engine generates a fixed event vocabulary (`AuthorizationEngineEvent`):

| Event | When |
|-------|------|
| `ROLE_RESOLVED` | roles + inheritance resolved into grants |
| `WILDCARD_EXPANDED` | a `*` / `resource.*` grant matched the requested code |
| `SCOPE_VALIDATED` | scope applicability was applied |
| `CONFLICT_RESOLVED` | allow/deny conflict resolved |
| `AUTHORIZATION_GRANTED` / `AUTHORIZATION_DENIED` | the outcome |
| `PERMISSION_CACHE_REFRESHED` | a cache miss rebuilt the identity's grants |

The two **outcome** events are the persisted audit: decisions are written to
`authorization_decisions` with timing. **Denials are always recorded**; allows on the
high-volume gate path are recorded only when `AUTHZ_LOG_ALLOW_DECISIONS` is on (to protect
the middleware budget); the `/check` endpoint always records. The **pipeline-step** events
are generated as a per-decision `trace` and returned on the `/authorization/check`
response (`events`) for observability, rather than one DB row per step per request.

See [permission resolution](permission-resolution.md), [wildcards](wildcards.md),
[scopes](scopes.md), [caching](caching.md).
