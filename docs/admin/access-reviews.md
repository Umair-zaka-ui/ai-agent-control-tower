# Access Review Campaigns

`/admin/reviews` — periodic certification of access (Phase 4.3.7 §14).
Requires `admin.reviews.manage`.

## Lifecycle

```
DRAFT → SCHEDULED → ACTIVE → COMPLETED → ARCHIVED
```

- **DRAFT** — name, description, scope (`role_ids`, `include_system_roles`),
  reviewer and deadline are editable.
- **ACTIVE** — activation *snapshots* every in-scope role assignment in the
  organization as a review item (subject, role, scope). New assignments made
  after activation are not silently added — they belong to the next campaign.
- **COMPLETED** — allowed only when every item is decided; enforced server-side.
- **ARCHIVED** — terminal; the record remains for audit.

Invalid transitions return `INVALID_LIFECYCLE_TRANSITION` (409).

## Decisions

Each item is **CERTIFIED** (access stays) or **REVOKED** with an optional
comment. A revoke is real enforcement: the underlying role assignment is
removed through the RBAC service — permission caches invalidate immediately and
the standard `ROLE_REMOVED` audit fires alongside
`ACCESS_REVIEW_ITEM_DECIDED`.

## Reporting

`GET /api/v1/admin/access-reviews/{id}/export` returns the campaign report
(items, decisions, comments, timestamps) and emits `AUDIT_EXPORTED`. The SPA
downloads it as JSON.

## Audit events

`ACCESS_REVIEW_CREATED`, `ACCESS_REVIEW_ACTIVATED`,
`ACCESS_REVIEW_ITEM_DECIDED`, `ACCESS_REVIEW_COMPLETED`,
`ACCESS_REVIEW_ARCHIVED`, `AUDIT_EXPORTED`.

## API

```
GET    /api/v1/admin/access-reviews[?status=]
POST   /api/v1/admin/access-reviews
GET    /api/v1/admin/access-reviews/{id}
PUT    /api/v1/admin/access-reviews/{id}            (DRAFT/SCHEDULED only)
POST   /api/v1/admin/access-reviews/{id}/schedule
POST   /api/v1/admin/access-reviews/{id}/activate
GET    /api/v1/admin/access-reviews/{id}/items
POST   /api/v1/admin/access-reviews/{id}/items/{item}/decide
POST   /api/v1/admin/access-reviews/{id}/complete
POST   /api/v1/admin/access-reviews/{id}/archive
GET    /api/v1/admin/access-reviews/{id}/export
```
