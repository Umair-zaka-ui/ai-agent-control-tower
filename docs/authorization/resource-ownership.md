# Resource ownership

Two layers cooperate here:

1. **Hierarchy attachment** (Phase 4.3.3, below) — *where* a resource sits in the
   org tree, feeding scoped-grant inheritance.
2. **Authorization ownership** (Phase 4.3.4, [next section](#authorization-ownership-phase-434-6-8))
   — *who* owns it, with owner types, audited transfers and preserved history.

## Hierarchy attachment (Phase 4.3.3 §6)

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

---

## Authorization ownership (Phase 4.3.4 §6–§8)

Every resource registered on the [`resources`](resource-authorization.md)
registry has **exactly one owner**: `owner_id` + `owner_type` (`USER`, `TEAM`,
`DEPARTMENT`, `ORGANIZATION`, `SERVICE_ACCOUNT`), plus `created_by`. Team and
department ownership resolve through membership — every member of the owning
team/department holds owner rights.

### What the owner may do (§7)

View, update, delete, share, manage the ACL, delegate, and transfer ownership.
The owner may **not** bypass global security policies: an explicit RBAC deny, an
ACL deny, or a resource policy binds the owner too.

### Transfers (§8)

`POST /api/v1/resources/{id}/transfer-ownership` — owner or `resource.manage`
only (`OWNER_TRANSFER_NOT_ALLOWED` otherwise). The new owner must exist inside
the resource's organization. Supported transitions cover every owner-type pair
(user → user, user → team, team → user, department → team,
organization → department, …).

Every transfer:

- is authorized;
- writes an `ownership_history` row (previous/new owner + types, actor, reason);
- emits `RESOURCE_OWNER_CHANGED` on the authorization audit trail.

`GET /api/v1/resources/{id}/ownership-history` returns the preserved history;
the Ownership transfer page (Settings → Security → Resources) renders it.
