# Orphaned Identity Detection

`/governance/orphaned-accounts` — Phase 4.3.8 §12. Requires
`governance.orphaned.manage`. Not in the SRS's exact doc list but documented
here alongside the rest of the detection subsystem.

## What `POST /orphaned-accounts/scan` checks

| Reason | Condition |
|---|---|
| `DISABLED_WITH_ACTIVE_ACCESS` | `User.is_active=false` but still holds `user_roles` rows. |
| `INACTIVE_OVER_90_DAYS` | No session activity (`auth_sessions.last_activity_at`, falling back to account creation) for 90+ days, while still holding role assignments. |
| `STALE_API_KEY` | An `ACTIVE` `AgentApiKey` unused (`last_used_at`) for 90+ days. |
| `UNUSED_ROLE` | An `ACTIVE` role in the organization with zero `user_roles` rows. |

Each match creates a `governance_findings` row
(`finding_type=ORPHANED_ACCOUNT`, `severity=MEDIUM`), deduplicated against
already-`OPEN` findings for the same (identity, resource) pair — re-scanning
is safe to call repeatedly (e.g. on a schedule external to this API).

`identity_id` is set for user-scoped findings (disabled/inactive); stale keys
and unused roles carry `resource_id` instead (the key or role id) with
`identity_id=null`.

## Audit events

`ORPHANED_ACCOUNT_DETECTED` — one per finding created.

## API

```
GET  /api/v1/governance/orphaned-accounts[?status=]
POST /api/v1/governance/orphaned-accounts/scan
```
