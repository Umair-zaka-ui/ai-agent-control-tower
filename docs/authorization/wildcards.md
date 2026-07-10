# Wildcard permissions (Phase 4.3.2 §13, §14)

A granted permission pattern can be concrete or a wildcard. Matching is done
server-side by `WildcardResolver.matches(pattern, code)`.

| Pattern | Matches |
|---------|---------|
| `agent.view` | exactly `agent.view` |
| `agent.*` | any action on `agent` — `agent.view`, `agent.create`, `agent.delete`, … (§13) |
| `*` | **everything** — the reserved global wildcard (§14) |

## The global wildcard `*`

`*` grants every permission. It is **reserved**: seeding grants it to
`ROLE_PLATFORM_OWNER` only, and it is deliberately kept out of the shared permission
catalog so no ordinary admin role can receive it. The `POST /api/v1/permissions` API
rejects `*` (and any non-`resource.action` name) via `INVALID_PERMISSION_NAME`.

## Why server-side

Wildcards are expanded and matched **only** on the server (§26). The client's `useCan`
mirrors the same rules for hiding controls, but it is a convenience — the server
re-evaluates every request and is the sole authority. A client that forges `["*"]`
locally still gets a 403 from the engine.

## Expansion vs matching

- **Matching** (the hot path) never enumerates the catalog — it is a cheap prefix test,
  so `agent.*` covering a brand-new `agent.foo` needs no data change.
- **Expansion** (`WildcardResolver.expand`) enumerates a wildcard against the known
  catalog and is used only for display/introspection.
