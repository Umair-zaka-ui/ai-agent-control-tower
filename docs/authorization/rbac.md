# Enterprise RBAC foundation (Phase 4.3.1)

Authentication proves *who you are*; authorization decides *what you may do*. This is
the RBAC foundation of the Enterprise Authorization Platform. It **extends** the
existing flat RBAC (`roles`, `rbac_permissions`, `user_roles`) rather than replacing
it — every existing login and permission check keeps working unchanged.

## Model

```
Identity ──< user_roles (scoped) >── Role ──< role_permissions >── RbacPermission ──> PermissionGroup
                                       │
                                  role_hierarchy (parent inherits child)
```

- **Role** — org-scoped or global (`organization_id IS NULL`) with `category`
  (SYSTEM/CUSTOM/ORGANIZATION/PROJECT/RESOURCE), `status` (lifecycle, §8), `priority`
  (0–100, conflict resolution §16), `is_system`, `is_assignable`.
- **RbacPermission** — the single-source `resource.action` catalog, each mapped to a
  **PermissionGroup** (domain) with a `resource_type`/`action` split.
- **user_roles** — a *scoped* assignment: GLOBAL / ORGANIZATION / DEPARTMENT / TEAM /
  PROJECT / RESOURCE, optionally time-boxed (`expires_at`).
- **role_hierarchy** — directed, acyclic edges; a parent (senior) role inherits every
  permission of its descendants (§17).
- **authorization_audit** — one row per administrative change *or* per-request decision.

See [roles](roles.md), [permissions](permissions.md), [role hierarchy](role-hierarchy.md).

## Principles (§3)

Business logic never branches on role names. It asks the permission catalog:

```python
# never:  if user.role == "admin"
# always: Depends(require_permission("agent.create"))
```

Roles are just bundles of permissions; the gate is always a permission code.

## Built-in taxonomy (§7)

18 global system roles ship seeded — Platform (Owner/Admin/Security Admin/Auditor/
Support), AI Ops (Operator/Reviewer/Policy/Model/Approval Manager), Organization
(Owner/Admin/Department Manager/Team Lead/User) and read-only (Viewer/Report Reader/
Analytics Viewer) — with priorities and a hierarchy. The four legacy roles
(SUPER_ADMIN/ADMIN/REVIEWER/VIEWER) remain and drive the existing per-org seeding.

Seeded idempotently by `app.authorization.seeding.seed_authorization` (run at app seed
time and in tests).

## API (§20)

All under `/api/v1`, permission-gated (`role.view` read, `role.manage` write,
`role.assign` for assignments):

`roles` · `roles/{id}` · `roles/{id}/effective-permissions` · `permissions` ·
`permission-groups` · `role-assignments` · `role-hierarchy` · `authorization/audit`.

Admin portal: **Settings → Security → Authorization** (Roles, Permissions,
Assignments, Hierarchy, Audit).

## Guarantees (§25)

System roles/permissions cannot be deleted; role names are unique within scope;
permission names are unique and validated (`resource.action`, lowercase, no spaces);
the hierarchy is kept acyclic; a role with live assignments cannot be deleted; every
change is audited.

## What's next

The stored model here feeds Phase 4.3.2 (the permission evaluation engine with
wildcards + cache), 4.3.3 (org hierarchy inheritance), 4.3.4 (resource-scoped checks)
and 4.3.5 (ABAC).
