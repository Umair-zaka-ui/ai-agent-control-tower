# Security Analytics Dashboard

`/admin/analytics` — operational security metrics for the authorization
platform (Phase 4.3.7 §17). Requires `admin.analytics.view`.

## Metrics

Denied requests (24h/7d), high-risk agent decisions (risk ≥ 70), MFA
challenges, approval volume and approval rate, pipeline latency (avg / p95),
decision-cache hit ratio, ABAC denies and challenges, and policy evaluation
errors.

## Visualizations

- **Denied requests trend** (7-day line)
- **Top denied permissions** (bar)
- **Resource sharing trend** (7-day line)

Counter metrics come from the 4.3.6 `PipelineMetricsService` and the 4.3.5
`ABACMetrics`; row-derived metrics are tenant-scoped, indexed queries.

## API

`GET /api/v1/admin/analytics` — refreshed by the SPA every 60 s (§24 budget:
under 2 s).
