# Delegated administration (Phase 4.3.3 §10, §19)

Administration is delegated *down* the hierarchy: a platform admin empowers an org admin,
who empowers a department manager, and so on — each with authority **only over their own
scope**.

```
Platform Admin → Organization Admin → Department Manager → Team Lead → Project Owner
```

## Model

A `delegations` row grants a **delegatee** administrative authority over a
`scope_type` (`ORGANIZATION` / `BUSINESS_UNIT` / `DEPARTMENT` / `TEAM` / `PROJECT`) and
`scope_id`, optionally narrowed to a single `permission`. It is active while
`revoked_at IS NULL`.

## Boundaries (§19)

`DelegationService.delegate` enforces that **a delegation cannot exceed the delegator's
own authority**:

- the delegated scope must resolve to the delegator's organization — delegating a
  department/team/project in another org is refused with `DELEGATION_EXCEEDS_AUTHORITY`;
- org-level delegation is pinned to the delegator's own organization.

## Effect on authorization

An active delegation into an organization is what lets a user cross the default
cross-organization isolation boundary (§9): the [engine](hierarchy-resolution.md) checks
`DelegationService.active_for_user` before denying a foreign-org resource check, and the
organization list/lookup includes orgs the caller holds a delegation into.

## API

```
GET    /api/v1/delegations              list (organization.view)
POST   /api/v1/delegations              delegate (organization.manage)
DELETE /api/v1/delegations/{id}         revoke (organization.manage)
```

Every delegate/revoke is audited (`DELEGATION_CREATED` / `DELEGATION_REVOKED`).
