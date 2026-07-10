# Roles (Phase 4.3.1)

A **role** is a named bundle of permissions, assignable to identities at a scope.

## Fields (§10)

| Field | Meaning |
|-------|---------|
| `organization_id` | owning org, or `NULL` for a **global** system role |
| `name` | unique within scope; immutable for system roles |
| `display_name` | human label |
| `category` | SYSTEM / CUSTOM / ORGANIZATION / PROJECT / RESOURCE (§9) |
| `status` | CREATED → ACTIVE → UPDATED → DEPRECATED → ARCHIVED → DELETED (§8) |
| `is_system` | shipped, protected from edit/delete |
| `is_assignable` | can receive new assignments (false once archived) |
| `priority` | 0–100; higher wins conflict resolution (§16) |

## Lifecycle (§8)

`CREATED → ACTIVE → UPDATED → DEPRECATED → ARCHIVED → DELETED`. A role may only be
**deleted when it has no assignments** (`ROLE_HAS_ASSIGNMENTS` otherwise). System roles
cannot be archived or deleted (`SYSTEM_ROLE_PROTECTED`). Deletion cascades the role's
permission grants and hierarchy edges; the audit trail retains the event.

## CRUD API

```
GET    /api/v1/roles            ?category= &status= &search=     (role.view)
POST   /api/v1/roles                                             (role.manage)
GET    /api/v1/roles/{id}                                        (role.view)
PUT    /api/v1/roles/{id}                                        (role.manage)
DELETE /api/v1/roles/{id}                                        (role.manage)
GET    /api/v1/roles/{id}/effective-permissions                 (role.view)
```

`POST`/`PUT` accept a `permissions: [codes]` set (rejected for system roles). The
effective-permissions endpoint returns the role's own permissions **plus** everything
inherited via the hierarchy.

## Errors

`ROLE_NOT_FOUND` (404), `ROLE_ALREADY_EXISTS` (409), `ROLE_HAS_ASSIGNMENTS` (409),
`SYSTEM_ROLE_PROTECTED` (403).
