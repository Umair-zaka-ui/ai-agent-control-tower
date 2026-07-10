# Role hierarchy (Phase 4.3.1 §17)

Roles can inherit from one another. An edge `(parent_role_id, child_role_id)` means the
**parent (senior) role inherits every permission of the child (junior) role**.

```
ROLE_PLATFORM_OWNER
      └─ ROLE_PLATFORM_ADMIN
             ├─ ROLE_SECURITY_ADMIN ─ ROLE_AUDITOR ─ ROLE_VIEWER
             └─ ROLE_ORG_ADMIN ─ ROLE_DEPARTMENT_MANAGER ─ ROLE_TEAM_LEAD ─ ROLE_USER ─ ROLE_VIEWER
```

> The SRS phrasing "child inherits parent permissions" is implemented as role
> **containment**: the senior/parent role's effective set is a superset of its
> children's. This is the standard RBAC/IAM direction and is what makes the priority
> ordering (Owner = 100 … Viewer = 10) consistent.

## Resolution

`GET /api/v1/roles/{id}/effective-permissions` returns:

```
effective(role) = own_permissions(role) ∪ ⋃ effective(child) for child in descendants(role)
```

computed by a breadth-first walk of the hierarchy graph.

## Acyclicity (§25)

The graph must stay a DAG. Before adding an edge `parent → child`, the service checks
whether `parent` is already reachable from `child`; if so (or `parent == child`) the
edge is rejected with `CIRCULAR_ROLE_HIERARCHY` (409). This covers both direct
(`A → A`) and transitive (`A → B → C`, then `C → A`) cycles.

## API

```
GET    /api/v1/role-hierarchy            (role.view)
POST   /api/v1/role-hierarchy            (role.manage)   { parent_role_id, child_role_id }
DELETE /api/v1/role-hierarchy/{id}       (role.manage)
```

## Errors

`ROLE_NOT_FOUND` (404), `CIRCULAR_ROLE_HIERARCHY` (409),
`ROLE_HIERARCHY_EDGE_NOT_FOUND` (404).
