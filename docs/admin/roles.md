# Roles & Permission Management

Phase 4.3.7 §7. The portal manages roles through two equivalent surfaces:

- **Settings → Security → Authorization** (Phase 4.3.1 pages): roles list,
  role details, create/edit, the permission catalog, permission groups, role
  assignments and the role hierarchy graph.
- **`/api/v1/admin/roles`** (§18): the portal-scoped delegation of the same
  `RoleService` — list/search, create, update, delete — gated by
  `admin.roles.manage` instead of `role.manage`, so enterprises can grant
  portal administration separately from raw RBAC administration.

Both surfaces share one implementation: inheritance, wildcards, explicit-deny
grants, system-role protection and cache invalidation behave identically, and
every change emits the standard audit events (`ROLE_CREATED`, `ROLE_UPDATED`,
`ROLE_DELETED`, `PERMISSION_ASSIGNED`, …).

`GET /api/v1/admin/permissions` (gated `admin.permissions.manage`) lists the
full permission catalog for pickers and matrices.

See [RBAC](../authorization/rbac.md), [roles](../authorization/roles.md) and
[permissions](../authorization/permissions.md) for the underlying model.
