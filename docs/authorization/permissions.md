# Permissions & groups (Phase 4.3.1)

## Naming convention (§11)

Every permission is `resource.action` — **lowercase, no spaces**, one dot. The action
may be `*` (a wildcard, evaluated from Phase 4.3.2). Validation rejects anything else
with `INVALID_PERMISSION_NAME` (422).

```
agent.create   policy.approve   audit.export   security.unlock   organization.manage
```

The `resource_type` (before the dot) and `action` (after) are stored split for fast
filtering and future wildcard resolution.

## Groups (§12)

Permissions are grouped by domain for the UI and for reasoning about scope:

`agents · policies · approvals · audit · security · organizations · analytics ·
authorization · general`

The mapping from a permission's `resource_type` to its group lives in
`app/authorization/catalog.py`; seeding backfills `group_id` on every catalog row.

## Catalog is single-sourced

Permission *codes* remain defined once in `app.services.rbac_service.PERMISSION_CATALOG`;
the authorization layer adds the group/resource metadata around them. Custom permissions
can be created at runtime (`POST /api/v1/permissions`, `role.manage`), but the shipped
`is_system` permissions cannot be deleted (`SYSTEM_ROLE_PROTECTED`).

## API

```
GET    /api/v1/permissions        ?group_id= &search=   (role.view)
POST   /api/v1/permissions                              (role.manage)
PUT    /api/v1/permissions/{id}                         (role.manage)
DELETE /api/v1/permissions/{id}                         (role.manage)
GET    /api/v1/permission-groups                        (role.view)
```

## Errors

`PERMISSION_NOT_FOUND` (404), `PERMISSION_ALREADY_EXISTS` (409),
`INVALID_PERMISSION_NAME` (422), `SYSTEM_ROLE_PROTECTED` (403 on deleting a system perm).
