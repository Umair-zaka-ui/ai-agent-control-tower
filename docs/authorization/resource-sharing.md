# Resource sharing (Phase 4.3.4 §12)

A share grants a **bundle of actions** on one resource to a user, team,
department or the whole organization — simpler than ACL entries for the common
"give Bob edit access" case. Stored on `resource_shares`, optionally expiring.

## Access levels

| Level | Actions covered |
| --- | --- |
| `READ` | view, read, list, get |
| `COMMENT` | READ + comment |
| `EXECUTE` | READ + execute, run, invoke, test |
| `EDIT` | COMMENT + EXECUTE + update, edit, write |
| `MANAGE` | every action **and** administering the resource's ACL/shares/delegations |

`MANAGE` deliberately does **not** include ownership transfer — that stays with
the owner and `resource.manage` holders (§8).

## Rules

- Shares never override an explicit ACL DENY or a resource policy (§11).
- **Cross-organization sharing is denied by default** (§22.4):
  the target must resolve inside the sharer's organization, otherwise
  `CROSS_ORGANIZATION_ACCESS_DENIED`.
- Expired shares are ignored at evaluation time; the UI marks them `expired`.
- Sharing, modifying and revoking require manage rights on the resource and are
  audited: `RESOURCE_SHARED` / `RESOURCE_SHARE_UPDATED` / `RESOURCE_UNSHARED`.

## API

```
GET    /api/v1/resources/{id}/shares
POST   /api/v1/resources/{id}/share
PUT    /api/v1/resources/{id}/share/{shareId}
DELETE /api/v1/resources/{id}/share/{shareId}
```

The UI (Settings → Security → Resources → Sharing) shows target, access level,
expiry and status, with share / level-change / revoke.
