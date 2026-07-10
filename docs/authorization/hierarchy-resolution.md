# Hierarchy resolution (Phase 4.3.3 §13, §14)

`HierarchyResolverService` turns an entity into its organizational path, and feeds that
path into the Permission Engine so a scoped grant applies via **downward inheritance**.

## Parent chain

`resolve_path(level, id)` walks up to the root:

```
project → team → department → business_unit → organization
```

returning a dict of every ancestor id, e.g. for a project:

```json
{ "organization_id": "…", "business_unit_id": "…",
  "department_id": "…", "team_id": "…", "project_id": "…" }
```

`has_children(level, id)` and the descendant walks power the "cannot delete a parent with
children" rule (§19).

## Downward inheritance in the engine (§7, §14)

When `/authorization/check` names a resource, the resource's ownership path is resolved
(`ResourceOwnershipService.resolve_path`) and packed into the engine's `ResourceContext`.
Because the context now carries the resource's **department, team and project**, a grant
scoped at any of those levels matches by exact per-level comparison — so a
`DEPARTMENT`-scoped role on department *D* authorizes a resource in any team/project
**below** *D*, but nothing outside it.

> John holds `ROLE_AI_OPERATOR` scoped to **Radiology**. An agent in project *Medical AI*
> (Radiology → AI Ops → Medical AI) resolves a path containing `department = Radiology`,
> so the grant applies. A Billing agent resolves a different department → denied.

## Cross-organization isolation (§9)

Before evaluating grants, if the resolved resource org ≠ the caller's org, the check is
**denied** unless the caller holds the global wildcard `*` or an active **delegation**
into that organization. This is what makes the platform multi-tenant-safe by default.

## Performance

Path resolution is a bounded walk (≤5 indexed `get`s); the tree is built with three
grouped queries. Targets (§20): resolution <25ms, inheritance <30ms, ownership <15ms,
tree <100ms — indexed for, surfaced via the check's `evaluation_time_ms`.
