# Organization hierarchy (Phase 4.3.3)

Enterprises are not a flat list of users. The platform models the full structure and
evaluates every authorization decision *within* it.

```
Platform
└── Organization
    └── Business Unit
        └── Department
            └── Team
                └── Project
                    └── Resources (agents, policies, workflows, …)
```

## Principles (§4)

- Every entity belongs to exactly one parent; a child inherits its parent's org context.
- **Permissions flow downward**; **isolation flows upward** (cross-org denied by default).
- Cross-boundary access requires explicit authorization (delegation).

## Schema (§11)

Extends the existing tenant model rather than replacing it:

| Table | Parent | Added |
|-------|--------|-------|
| `organizations` | — | `slug`, `owner_id` |
| `business_units` | organization | *new* |
| `departments` | organization (+ optional `business_unit_id`) | `business_unit_id`, `status` |
| `teams` | department | `status` |
| `projects` | team | *new* |
| `resource_ownership` | — | *new* — a resource's full path + owner |
| `delegations` | — | *new* — delegated administration |

## API (§15)

CRUD under `/api/v1` for `organizations`, `business-units`, `departments`, `teams`,
`projects`; the tree at `GET /api/v1/hierarchy/tree`; ownership under
`/api/v1/resource-ownership`; delegation under `/api/v1/delegations`. Reads need
`organization.view`, writes `organization.manage`. Admin portal:
**Settings → Security → Organization** (Explorer, Business units, Departments, Teams,
Projects, Delegation).

## Guarantees (§19)

Cross-org access is denied by default (a foreign entity answers *404*, never "exists but
not yours"); a parent with children cannot be deleted until they are reassigned/removed
(`ENTITY_HAS_CHILDREN`); organizations are archived, never hard-deleted; every change is
audited to `authorization_audit` (§18). See
[hierarchy resolution](hierarchy-resolution.md), [resource ownership](resource-ownership.md),
[delegated administration](delegated-administration.md).
