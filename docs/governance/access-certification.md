# Access Certification Campaigns

`/governance/campaigns` + `/governance/campaigns/:id` (review) — periodic
certification of access (Phase 4.3.8 §5-§7). Requires
`governance.certification.manage`.

This reuses the Phase 4.3.7 `AccessReviewService` wholesale — same lifecycle,
enforcement and audit trail as `/api/v1/admin/access-reviews` (see
[docs/admin/access-reviews.md](../admin/access-reviews.md)) — behind the
`/api/v1/governance/campaigns` surface, extended with a `campaign_type` and a
richer decision vocabulary.

## Campaign types

`QUARTERLY` (default) · `ANNUAL` · `PRIVILEGED` · `PROJECT` · `EMERGENCY`.
Purely descriptive metadata — scope and lifecycle behave identically for
every type.

## Lifecycle

```
DRAFT → SCHEDULED → ACTIVE → COMPLETED → ARCHIVED
```

`POST /campaigns/{id}/launch` schedules (if still `DRAFT`) then activates in
one call, snapshotting every in-scope role assignment as a review item.
`COMPLETED` requires every item decided; decisions are immutable once
`COMPLETED` (`CERTIFICATION_DECISION_IMMUTABLE`, 409).

## Decisions

Each item takes one of:

- **CERTIFIED** (`POST /reviews/{item}/approve`) — access stays.
- **REVOKED** (`POST /reviews/{item}/revoke`) — real enforcement: the
  underlying role assignment is removed through the RBAC service.
- **MODIFIED** (`POST /reviews/{item}/modify`) — certified with a follow-up
  note; access stays, flagged for a scoped follow-up outside this campaign.
- **DELEGATED** (`POST /reviews/{item}/delegate`) — reassigned to another
  reviewer; the delegate id is recorded in the item's comment.

All four accept an optional `comment` (justification).

## Audit events

`CERTIFICATION_CREATED`, `CERTIFICATION_COMPLETED`, `ACCESS_APPROVED`,
`ACCESS_REVOKED`, plus the underlying `ACCESS_REVIEW_*` events from the
4.3.7 engine.

## API

```
GET    /api/v1/governance/campaigns[?status=]
POST   /api/v1/governance/campaigns
GET    /api/v1/governance/campaigns/{id}
PUT    /api/v1/governance/campaigns/{id}            (DRAFT/SCHEDULED only)
POST   /api/v1/governance/campaigns/{id}/launch
GET    /api/v1/governance/campaigns/{id}/items
POST   /api/v1/governance/campaigns/{id}/complete
POST   /api/v1/governance/campaigns/{id}/archive
GET    /api/v1/governance/campaigns/{id}/export
POST   /api/v1/governance/reviews/{item}/approve
POST   /api/v1/governance/reviews/{item}/revoke
POST   /api/v1/governance/reviews/{item}/modify
POST   /api/v1/governance/reviews/{item}/delegate
```
