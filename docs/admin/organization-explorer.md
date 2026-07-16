# Organization Hierarchy Explorer

Phase 4.3.7 §8. The explorer visualizes the full enterprise structure —
Organization → Business Unit → Department → Team → Project → Resources — with
expand/collapse, search, ownership indicators and statistics.

- **Portal page**: Settings → Security → Organization → Hierarchy explorer
  (Phase 4.3.3), plus the Business units / Departments / Teams / Projects /
  Delegation management pages.
- **Portal API**: `GET /api/v1/admin/organizations` (gated
  `admin.organizations.manage`) returns the same tree the explorer renders,
  scoped to the administrator's organization.

Permission inheritance follows the tree downward (a department-scoped grant
authorizes its teams and projects); cross-organization isolation is enforced
upward. See [organization hierarchy](../authorization/organization-hierarchy.md)
and [hierarchy resolution](../authorization/hierarchy-resolution.md).
