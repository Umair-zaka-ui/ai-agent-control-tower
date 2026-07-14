# Resource delegation (Phase 4.3.4 §13)

An owner (or resource administrator) hands a **specific set of actions on one
resource** to another user, optionally time-boxed:

```
Alice owns Agent A → delegates "manage" → Bob → 30 days
```

Stored on `resource_delegations`: delegate, permissions (JSON list of actions or
codes; `"manage"` covers every action), expiry, status (`ACTIVE`/`REVOKED`),
reason and approver.

> Not to be confused with Phase 4.3.3
> [delegated administration](delegated-administration.md), which delegates
> *organizational scope* (a department, a team). This delegates *one resource*.

## Rules

- The delegate must belong to the resource's organization
  (`CROSS_ORGANIZATION_ACCESS_DENIED` otherwise).
- Creating a delegation whose expiry is already past is rejected with
  `DELEGATION_EXPIRED` (410).
- Expired delegations are ignored at evaluation time (§22.6); revoked ones stay
  listed for audit.
- A `"manage"` delegation also lets the delegate administer the resource's ACL,
  shares and delegations — but **not** transfer ownership.
- A delegation never overrides an explicit ACL DENY or a resource policy.
- Create/revoke are audited: `RESOURCE_DELEGATED` /
  `RESOURCE_DELEGATION_REVOKED`, with delegate, permissions and reason.

## API

```
GET    /api/v1/resources/{id}/delegations
POST   /api/v1/resources/{id}/delegate
DELETE /api/v1/resources/{id}/delegate/{delegationId}
```

The UI (Settings → Security → Resources → Delegation) creates time-boxed
delegations with a reason and revokes active ones.
