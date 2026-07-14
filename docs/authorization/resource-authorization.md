# Resource-based authorization (Phase 4.3.4)

Traditional RBAC answers "may this role do X?". Phase 4.3.4 makes the platform
answer "may this identity do X **to this resource**?" — two users with identical
roles can get different decisions based on ownership, ACLs, delegation, sharing,
visibility, organizational context and resource-specific policy.

## The registry

Every protected object (agent, prompt, workflow, policy, dataset, dashboard,
connector, …; §3 lists 15 built-in types, and `resource_type` is a free-form
string so new types register without an engine change) gets one row in
`resources`:

```
resource_type + resource_id → owner (id + type), visibility, status, policy
```

The registry row's primary key is the handle used by the `/api/v1/resources/*`
API. `(resource_type, resource_id)` links it to the underlying platform object
and to its Phase 4.3.3 [ownership path](resource-ownership.md), which supplies
the department/team context for scoped grants and visibility.

## Evaluation order (§5, §18)

`ResourceAuthorizationService.authorize(identity, permission, resource)` runs:

1. **Identity** — verified by the route (`get_current_user`).
2. **Organization scope** — a foreign-org resource is denied
   (`CROSS_ORGANIZATION_ACCESS_DENIED`) unless the caller holds the global `*`
   grant, or the resource is `PUBLIC_INTERNAL` and the action is a read.
3. **Roles / inherited permissions** — the Phase 4.3.2
   [Permission Engine](permission-engine.md) evaluates the role decision over the
   resource's hierarchy path. An **explicit role deny ends evaluation** — nobody,
   including the owner, bypasses a global security policy (§7).
4. **ACL DENY** — an explicit, unexpired [ACL](resource-acl.md) deny ends
   evaluation (§11: deny always overrides allow).
5. **Resource policy** — a [policy rule](#resource-policy-14) naming the
   permission restricts it to matching principals (`RESOURCE_POLICY_DENIED`
   otherwise). Policies bind even the owner.
6. **Ownership** — the owner may do everything on their resource.
7. **ACL ALLOW** — explicit allow.
8. **Delegation** — an active, unexpired [delegation](delegation.md) covering the
   action.
9. **Sharing** — an unexpired [share](resource-sharing.md) whose access level
   covers the action.
10. **Role allow** — the inherited RBAC permission.
11. **Visibility** — read actions only: `TEAM` / `DEPARTMENT` /
    `ORGANIZATION` / `PUBLIC_INTERNAL` grant view to the matching population.
12. **Default DENY** (§22.7).

The decision carries the source (`OWNER`, `ACL`, `DELEGATION`, `SHARE`, `ROLE`,
`VISIBILITY`, `…_DENY`), the matched rule id, and the ordered evaluation steps —
which is exactly what the **Authorization Inspector** renders.

## Visibility levels (§9)

| Level | Who can read |
| --- | --- |
| `PRIVATE` | owner + explicit ACL/share/delegation only |
| `TEAM` | members of the resource's team (from its 4.3.3 path) |
| `DEPARTMENT` | members of the resource's department |
| `ORGANIZATION` | everyone in the resource's organization |
| `PUBLIC_INTERNAL` | every authenticated platform user (never internet-facing) |

Visibility grants **reads only** — writes always need ownership, an ACL entry,
a delegation, a share at EDIT/MANAGE, or a role grant.

## Resource policy (§14)

`resources.policy` is an optional list of rules:

```json
[{"permission": "agent.publish", "principal_type": "TEAM", "principal_id": "<compliance-team>"}]
```

When any rule names the requested permission, only matching principals may
perform it — evaluated after role permissions, before every allow path.
Updating a policy is audited (`RESOURCE_POLICY_UPDATED`).

## Engine integration (§18)

`POST /api/v1/authorization/check` detects a *registered* resource and routes
the decision through the full chain above; unregistered resources keep the pure
Phase 4.3.2/4.3.3 role + scope path. Both paths record their decision.

## Membership resolution

ACL entries, shares and policies name principals. An identity matches:

- `USER` / `SERVICE_ACCOUNT` — its own id;
- `ROLE` — an active assignment of that role;
- `DEPARTMENT` — its own department, a department it manages, or a
  department-scoped role assignment;
- `TEAM` — a team it leads or a team-scoped role assignment;
- `ORGANIZATION` — its organization id.

## Security requirements (§22)

- On **SYSTEM** resources, a DENY entry may not target a platform administrator
  (a `*` grant holder) — rejected at write time and ignored at evaluation time.
- ACL / share / delegation mutations require the owner, a MANAGE share, a manage
  delegation, or the `resource.manage` permission.
- Ownership transfer is stricter: owner or `resource.manage` only.
- Cross-organization lookups answer **404** (existence is not revealed);
  cross-organization sharing is rejected.
- Expired ACL entries, shares and delegations are ignored.
- Default outcome is DENY; every decision through `/resources/{id}/authorize`
  is audited (`RESOURCE_ACCESS_GRANTED` / `RESOURCE_ACCESS_DENIED`).

## API surface (§19)

Registry: `GET/POST /api/v1/resources`, `GET /resources/types`,
`GET/PUT /resources/{id}`. Ownership: `GET /resources/{id}/owner`,
`POST /resources/{id}/transfer-ownership`, `GET /resources/{id}/ownership-history`.
ACL: `GET/POST /resources/{id}/acl`, `PUT/DELETE /resources/{id}/acl/{aclId}`.
Sharing: `GET /resources/{id}/shares`, `POST /resources/{id}/share`,
`PUT/DELETE /resources/{id}/share/{shareId}`. Delegation:
`GET /resources/{id}/delegations`, `POST /resources/{id}/delegate`,
`DELETE /resources/{id}/delegate/{delegationId}`. Policy:
`PUT /resources/{id}/policy`. Decision: `POST /resources/{id}/authorize`
(with `identity_id` simulation for `resource.manage` holders — the inspector).

## Error codes (§24)

`RESOURCE_NOT_FOUND` (404), `RESOURCE_OWNER_REQUIRED` (403),
`ACL_ENTRY_NOT_FOUND` (404), `RESOURCE_NOT_SHARED` (404),
`DELEGATION_EXPIRED` (410), `OWNER_TRANSFER_NOT_ALLOWED` (403),
`RESOURCE_POLICY_DENIED` (403), `CROSS_ORGANIZATION_ACCESS_DENIED` (403),
`RESOURCE_ACCESS_DENIED` (403).

## Frontend (§20, §21)

Settings → Security → **Resources**: Resource permissions (registry +
visibility), ACL, Sharing, Ownership transfer (+history), Delegation, and the
Authorization Inspector (identity + resource + permission → ALLOW/DENY with
reason, source, owner, visibility, scope and evaluation steps).
