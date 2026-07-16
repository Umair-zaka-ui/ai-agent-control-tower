# ABAC Policy Management & Visual Builder

Phase 4.3.7 §10–§11. Policy lifecycle management lives on the Phase 4.3.5
pages (`/authorization/abac`): list with search/filter, details, versions with
rollback, validation, publishing, cloning and archive.

## Visual Policy Builder

`/authorization/abac/new` (and edit) — constructs valid policy JSON without
exposing implementation details:

- policy metadata, scope selector, target selector,
- nested ALL/ANY condition groups,
- attribute browser (only registered attributes appear),
- operator selector (only operators the attribute supports),
- typed value editors,
- effect and obligation configuration,
- validation panel and a human-readable live preview
  (*IF resource contains PHI AND device is not trusted THEN deny*).

Raw JSON editing remains available for advanced administrators.

## Portal API

`/api/v1/admin/policies` (gated `admin.policies.manage`) delegates
list/create/update/delete to the same `PolicyService` — draft-only edits,
publish-time validation/compilation and immutable version history are
identical. Publishing itself stays on the ABAC lifecycle endpoints and
requires `authorization.abac.publish`, keeping author/publisher separation of
duties intact (§23).

See [policy language](../authorization/abac/policy-language.md) and
[policy lifecycle](../authorization/abac/policy-lifecycle.md).
