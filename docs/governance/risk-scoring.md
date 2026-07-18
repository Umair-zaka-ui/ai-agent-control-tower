# Governance Risk Scoring

`/governance/analytics` — Phase 4.3.8 §13. Reading scores requires
`governance.analytics.view`.

## Factors

`GovernanceRiskScoringService.compute_for_identity` (in
`app/governance/services.py`) sums five weighted factors, capped at 100:

| Factor | Weight | Cap |
|---|---|---|
| Privileged roles held | 15/role | 30 |
| Open SoD/toxic-permission findings | 15/finding | 30 |
| Inactivity beyond 90 days | 5 per 30-day block over the threshold | 20 |
| Failed certifications (`REVOKED` review items) | 5/item | 10 |
| Outstanding pending approvals assigned to the identity | 2/item | 10 |

**Documented gaps:** MFA status and "high-risk resources accessed" are named
in the SRS (§13) but not implemented — this codebase has no persistent
per-user MFA-enabled flag or a resource risk signal keyed to a human
identity yet. Adding either is additive: a new factor in
`compute_for_identity` plus a schema field once the underlying signal exists.

## Bands

`0-20 LOW` · `21-50 MEDIUM` · `51-80 HIGH` · `81-100 CRITICAL`.

## Computation

Scores are recomputed on demand, never on a schedule:

- `POST /risk-scores/recalculate` — every active user in the org.
- `GET /privileged-accounts` computes (and upserts) a score for any
  privileged identity that doesn't have one yet.

Each computation upserts one `governance_risk_scores` row per
(organization, identity) — `GET /risk-scores` always reads the latest
snapshot, not a live recomputation.

## Audit events

`RISK_SCORE_COMPUTED` (once per `compute_all` call, not per identity).

## API

```
GET  /api/v1/governance/risk-scores[?band=]
POST /api/v1/governance/risk-scores/recalculate
```
