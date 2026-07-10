# Resource ownership (Phase 4.3.3 §6)

Every protected resource (agent, policy, workflow, dashboard, …) can be attached to the
organizational hierarchy through one `resource_ownership` row.

## What it records

```
resource_type + resource_id  →  organization / business_unit / department / team / project / owner
```

`ResourceOwnershipService.assign` derives the full path from the **deepest** entity you
supply (a `project_id` fills in its team/department/organization automatically) and stores
it, all resolving to the caller's organization (§9). One row per `(resource_type,
resource_id)` — re-assigning updates it.

## Why it matters

The stored path is the input the [engine](hierarchy-resolution.md) uses to decide whether a
scoped grant applies to a resource. Without ownership, a resource is treated as org-level
only; with it, department/team/project-scoped roles authorize it precisely.

## Transfers (§19)

`POST /api/v1/resource-ownership/transfer` changes the `owner_id`. Ownership transfers
require `organization.manage` and are audited (`OWNERSHIP_TRANSFERRED`), recording the
previous and new owner. A resource in another organization cannot be transferred (§9).

## API

```
POST /api/v1/resource-ownership            assign / re-attach   (organization.manage)
POST /api/v1/resource-ownership/transfer   change owner         (organization.manage)
GET  /api/v1/resource-ownership/{type}/{id}  resolve path       (organization.view)
```
