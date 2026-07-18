# Privileged Access Governance

`/governance/privileged-access` — Phase 4.3.8 §11. Requires
`governance.privileged.manage`.

## Tracked roles

`PRIVILEGED_ROLE_NAMES` in `app/governance/services.py`:
`ROLE_PLATFORM_OWNER`, `ROLE_PLATFORM_ADMIN`, `ROLE_SECURITY_ADMIN`,
`ROLE_ORG_ADMIN`, `ROLE_COMPLIANCE_ADMIN` (new builtin role, Phase 4.3.8 —
see `app/authorization/catalog.py`), and the legacy `SUPER_ADMIN`/`ADMIN`
roles.

**Gap:** system service accounts are a distinct identity type from `User` in
this codebase and are not yet enumerated here — `GET /privileged-accounts`
only covers human identities holding a tracked role. Extending it to service
accounts is a follow-up, not a silent omission.

## Listing

`GET /privileged-accounts` joins every tracked-role assignment to its
identity, with a live (or freshly-computed) governance risk score, last
session activity, and the most recent review's status/due date if one exists.

## Review workflow

1. `POST /privileged-accounts/reviews` (query params `identity_id`,
   `role_name`, optional `assignment_id`) creates a `PENDING` review, snapshotting
   the current risk score.
2. `POST /privileged-accounts/reviews/{id}/decide` (query params `decision`
   = `APPROVED`|`REVOKED`, optional `assignment_id`) records the decision. A
   `REVOKED` decision with an `assignment_id` removes the grant through the
   RBAC service — real enforcement, same pattern as certification revokes.

## Audit events

`PRIVILEGED_REVIEW_COMPLETED`.

## API

```
GET  /api/v1/governance/privileged-accounts
POST /api/v1/governance/privileged-accounts/reviews
GET  /api/v1/governance/privileged-accounts/reviews[?status=]
POST /api/v1/governance/privileged-accounts/reviews/{id}/decide
```
