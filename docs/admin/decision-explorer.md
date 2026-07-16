# Authorization Decision Explorer

`/admin/decisions` — investigate why authorization decisions were made
(Phase 4.3.7 §13). Requires `admin.audit.view`.

## Filters

Identity, permission (substring), resource type, decision (allowed/denied) and
time range, capped at 500 rows per query. Results are strictly tenant-scoped —
another organization's decisions are invisible by construction.

## Display

Each row shows the permission, timestamp, evaluation latency and source role;
expanding a row reveals the reason, scope, identity, resource and request id
(the key into the full pipeline trace stored with the `DECISION_GENERATED`
audit event from Phase 4.3.6).

## Auditing the auditors

Every explorer query emits a `DECISION_VIEWED` audit event recording the
filters used and the number of rows returned (§22).

## API

`GET /api/v1/admin/authorization-decisions?identity_id=&permission=&resource_type=&allowed=&since=&until=&limit=`
