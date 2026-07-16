# Resource Permission Administration

Phase 4.3.7 §9. Per-resource authorization is administered through the
Phase 4.3.4 portal pages — Settings → Security → Resources:

- **Resource browser / registry** — every protected resource with visibility
  and status.
- **Ownership** — view and transfer ownership (history preserved).
- **ACL** — per-principal allow/deny entries with expiry; explicit deny wins.
- **Sharing** — READ → MANAGE shares for users/teams/departments/org.
- **Delegation** — time-boxed delegated access, revocable.
- **Authorization Inspector** — simulate identity × resource × permission and
  see the full decision chain.

The portal API adds `GET /api/v1/admin/resources` (gated
`admin.resources.manage`) — the tenant-wide registry listing that backs the
admin resource browser regardless of per-resource view rights.

Every mutation is audited (`RESOURCE_SHARED`, `RESOURCE_OWNER_CHANGED`,
`RESOURCE_ACL_*`, `RESOURCE_DELEGATED`, …). See
[resource authorization](../authorization/resource-authorization.md).
