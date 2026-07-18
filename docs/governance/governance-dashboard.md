# Governance Dashboard

`/governance` — Phase 4.3.8 §21, §26. Requires `governance.dashboard.view`
(dashboard) / `governance.analytics.view` (analytics).

## Widgets (`GET /dashboard`)

`active_campaigns`, `pending_reviews`, `overdue_reviews` (active campaigns
past `due_at`), `privileged_accounts` (distinct identities holding a tracked
privileged role — see [privileged-access.md](privileged-access.md)),
`toxic_permission_findings`, `sod_findings`, `orphaned_accounts` (all three
`OPEN`-status counts), `compliance_status` (`ready` once at least one
compliance report has been generated, else `no_reports_yet`),
`remediation_queue` (`PENDING` remediation actions), and
`governance_risk_distribution` (band → count).

## Charts (`GET /analytics`, also embedded as `dashboard.charts`)

- `review_completion_trend` — campaigns completed per day, last 30 days.
- `findings_by_severity` / `findings_by_type` — open findings breakdown.
- `privileged_access_growth` — privileged role assignments per month, last
  30 days.
- `risk_score_distribution` — the same risk-band distribution as the
  dashboard widget, exposed as a chart series.

All of this is computed live from the current tables on every request — there
is no caching layer or scheduled aggregation job. At current expected data
volumes (SRS §25 targets <2s for the dashboard) this is fine; if governance
tables grow large, this is the first place to add materialized aggregates.

## API

```
GET /api/v1/governance/dashboard
GET /api/v1/governance/analytics
```
