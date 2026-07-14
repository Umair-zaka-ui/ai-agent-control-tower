# Resource ACLs (Phase 4.3.4 §10, §11)

Each protected resource carries an access control list on `resource_acl`. One
entry grants or denies one permission to one principal, optionally until an
expiry:

```
principal_type + principal_id  →  permission  →  ALLOW | DENY  (expires_at?)
```

- **Principals**: `USER`, `ROLE`, `TEAM`, `DEPARTMENT`, `ORGANIZATION`,
  `SERVICE_ACCOUNT` (membership rules in
  [resource-authorization.md](resource-authorization.md#membership-resolution)).
- **Permission** may be a full code (`agent.update`), a bare action (`update`),
  or `*` (every action on the resource).

## Evaluation priority (§11)

```
Explicit DENY → Explicit ALLOW → Inherited role permission → Visibility → Default DENY
```

An explicit DENY always overrides every allow — including ownership. The only
exception (§22.1): on a **SYSTEM** resource a DENY never binds a platform
administrator, and creating such an entry is rejected
(`SYSTEM_ROLE_PROTECTED`).

Expired entries are ignored at evaluation time (§22.5); they remain listed so
administrators can see and clean them up.

## Who may edit an ACL

The resource owner, a MANAGE-level share holder, a manage delegate, or a
`resource.manage` holder (§22.2). Everyone else gets
`RESOURCE_OWNER_REQUIRED` (403).

Every mutation is audited: `RESOURCE_ACL_CREATED` / `RESOURCE_ACL_UPDATED` /
`RESOURCE_ACL_DELETED` on `authorization_audit`, with the resource, principal,
permission and effect in the metadata.

## API

```
GET    /api/v1/resources/{id}/acl
POST   /api/v1/resources/{id}/acl
PUT    /api/v1/resources/{id}/acl/{aclId}
DELETE /api/v1/resources/{id}/acl/{aclId}
```

The UI (Settings → Security → Resources → ACL) shows principal, permission,
effect, expiry and creator, with add / effect-toggle / delete and search.
