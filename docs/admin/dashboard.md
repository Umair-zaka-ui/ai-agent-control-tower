# Administration Dashboard

`/admin` — the operational overview of authorization health (Phase 4.3.7 §6).
Requires `admin.dashboard.view`.

## Widgets

Total users, active roles, active permissions, active ABAC policies, active
sessions, authorization requests (24h), denied requests (24h), pending
approvals, MFA challenges, high-risk decisions (24h, agent risk ≥ 70), the
decision-cache hit ratio and the average pipeline evaluation latency.

Counts are tenant-scoped to the administrator's organization; cache/latency
metrics come from the 4.3.6 pipeline metrics service.

## Charts

- **Authorization trend (7d)** — total vs denied decisions per day.
- **Top requested permissions** — request/deny counts per permission.
- **Policy matches** — which ABAC policies are actually firing.
- **Decision breakdown** — ALLOW / DENY / challenge distribution.
- **Approval queue** — pending/approved/rejected/escalated counts.

## API

`GET /api/v1/admin/dashboard` → `{widgets, charts}`. The §24 budget is a
sub-2-second load; the backend answers from indexed, bounded queries plus
in-process metrics, and the SPA refreshes every 60 s.
