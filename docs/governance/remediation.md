# Automated Remediation

`/governance/remediation` — Phase 4.3.8 §14. Requires
`governance.remediation.manage`.

## Model

A `remediation_actions` row targets exactly one `governance_findings` row.
`mode` is `MANUAL` (created, then executed by an operator),
`APPROVAL` (recorded but not auto-executed — approval is tracked via the
finding/action status, no separate approval-request record exists yet), or
`AUTOMATIC` (executed immediately on creation).

## Action types and what they actually do

| Action | Executes against live state? |
|---|---|
| `REMOVE_ROLE` | Yes — `payload.assignment_id` is removed through `RoleAssignmentService`, same enforcement path as a certification revoke. |
| `DISABLE_ACCOUNT` | Yes — sets `User.is_active=false`, `status=DISABLED`. |
| `DISABLE_API_KEY` | Yes — `payload.api_key_id` is set to `ApiKeyStatus.REVOKED`. |
| `EXPIRE_DELEGATION` | Yes — `payload.delegation_id`'s `revoked_at` is stamped. |
| `NOTIFY_MANAGER` | **No** — no manager hierarchy exists on `User` yet. Recorded as `EXECUTED` in the audit trail only. |
| `CREATE_APPROVAL_REQUEST` | **No** — the platform's `Approval` model requires an `agent_action_id`, which doesn't exist for a governance finding. Recorded via the audit trail only. |
| `REQUIRE_MFA` | **No** — no persistent per-user "MFA required" flag exists yet. Recorded via the audit trail only. |
| `CREATE_SECURITY_TICKET` | **No** — no ticketing integration exists. Recorded via the audit trail only. |

The four "No" rows are honest gaps, not silent no-ops: every remediation
action is always visible in `remediation_actions` and the audit trail
regardless of whether it changed live state, so nothing is lost — only the
downstream system integration is missing. Wiring one in is additive: extend
`RemediationService._dispatch` in `app/governance/services.py`.

## Executing

`POST /remediation-actions/{id}/execute` dispatches by `action_type`,  sets
`status=EXECUTED` on success or `FAILED` on error (re-raising), and always
stamps `executed_by`/`executed_at`. An already-`EXECUTED` action cannot be
re-executed (`REMEDIATION_ALREADY_EXECUTED`, 409).

## Audit events

`REMEDIATION_CREATED`, `REMEDIATION_EXECUTED`.

## API

```
GET  /api/v1/governance/remediation-actions[?status=&finding_id=]
POST /api/v1/governance/remediation-actions
POST /api/v1/governance/remediation-actions/{id}/execute
```

Related: [governance-dashboard.md](governance-dashboard.md) surfaces the
`PENDING` remediation queue; findings link to this page via
`GET /findings` (see [docs/governance/access-certification.md](access-certification.md)
for certification, or the SoD/toxic/orphaned docs for how findings arrive).
