# Cost governance — real spend, provenance, and the legacy estimate

> **Phase 4.4 (ACT-SRS-M4 §4.4, §10).** Where the platform's cost figures come
> from, why there are two of them and only one is real, and how a charge from
> last month stays reconstructable after prices change. Budgets are in
> [budgets.md](./budgets.md).

## Two cost figures, and which one to believe

| | `GET /api/v1/cost/summary` | `GET /analytics/cost` |
|---|---|---|
| Source | `agent_executions.cost_amount` | `agent_actions` row counts |
| Computed by | `PricingService` at execution time | flat placeholder constants |
| Relationship to real spend | **is** real spend | none |
| Status | **canonical** | **deprecated in place** |

The legacy figure multiplies row counts by constants like
`_COST_PER_ACTION = 0.012` and `_HUMAN_REVIEW_HOURLY = 65.0`. It has always
returned `estimated: true`, which was honest — but a field called `estimated`
sitting next to a field called `total` is easy to miss, so as of Phase 4.4 the
response also carries a `deprecation` object naming the replacement.

**It was not rewired, deliberately.** The Phase-3 dashboard consuming it
expects six synthetic categories — human review, policy evaluation, storage —
none of which `agent_executions` knows anything about. Pointing it at real data
would have silently redefined every number on a dashboard this phase does not
own, mid-milestone. It keeps working exactly as it did and now says what it is.
Removal is scheduled for when the Phase 4.9 observability center replaces that
dashboard.

Note the path: `/analytics/cost`, **not** `/api/v1/analytics/cost`. The Phase-3
analytics router is mounted through `api_router` with `settings.API_PREFIX`,
which is the empty string.

## Actual, estimated, and unpriced are three numbers

Every aggregate returns them separately and never adds them:

- **`actual_amount`** — executions with a real metered cost.
- **`estimated_amount`** — executions where `cost_is_estimated` is true.
- **`unpriced_execution_count`** — executions with no `cost_amount` at all,
  because the provider reported no usage or no pricing row matched.

Summing these into one figure labelled "spend" would produce a number an
operator takes to their finance team. The third is the one most easily lost:
treating "we don't know" as zero is how a spend figure becomes a lie that gets
repeated.

## Dimensions

`agent`, `agent_version`, `environment`, `provider`, `model`, `project`,
`department`, `status` — plus time, via `/cost/timeseries` at hour, day or
month granularity.

The list is **bounded on purpose**. An open `group_by` over caller-supplied
column names is a SQL-injection surface and an unbounded-cardinality surface at
once; an unknown dimension is refused rather than ignored.

Three of them are not columns on `agent_executions` — `environment` lives on
the deployment, `provider`/`model` in the version's `model_configuration`
JSONB, `project`/`department` on the agent. Filters compile them as correlated
`EXISTS` (a join would multiply rows and then need a `DISTINCT`); *breakdowns*
must join, because a grouping key has to be selected rather than merely tested
for. Both sides are primary-key joins with the tenant predicate already
narrowing the driving side.

## Provenance is immutable (§10)

`GET /api/v1/cost/executions/{id}/provenance` returns the provider, model,
`pricing_version`, token counts, calculated amount, currency and timestamp for
one charge.

**A price change never rewrites a historical cost**, and that is a property of
how pricing was already built rather than something this phase adds:
`PricingService.set_price` closes the prior price row and inserts a new one
instead of mutating in place, and the execution records the `pricing_version`
that produced its amount. Ten-x-ing a model's price today leaves last month's
charges, and every aggregate over them, exactly as they were. There is a test
that would fail loudly if either half ever became an in-place update.

## Spend anomalies

The rule, in full, because a cost alert nobody can reproduce by hand is a cost
alert nobody trusts:

> A period is anomalous when its actual spend exceeds `threshold_ratio` times
> the mean of the periods before it.

Every anomaly returns the amount, the baseline, the ratio and the threshold
that produced the verdict. `min_baseline` exists because ratios are meaningless
against almost nothing — $0.02 following a $0.001 day is a 20× "spike" and is
noise. Phase 3.5's canary health has an `INSUFFICIENT_DATA` floor for the same
reason.

No model, no training data, no learned threshold; a test asserts the module
imports no numerical or ML library. Behavioural anomaly detection is Phase
4.5's, and it is a different kind of claim.

## Performance, measured

Against 109,398 executions (8,627 priced) across 10,934 tenants, busiest tenant
500 rows:

| Query | p50 | p95 |
|---|---|---|
| summary, 30-day window, no breakdown | **0.80 ms** | 0.91 ms |
| summary by agent / model / provider / project | 1.99 – 2.30 ms | ≤ 3.5 ms |
| summary by environment (deployment join) | 5.69 ms | 6.54 ms |
| timeseries, daily buckets | 1.11 ms | 1.63 ms |
| anomaly scan over that series | 1.04 ms | 1.33 ms |

Every one reaches its rows through an existing index — Phase 4.2's
`ix_agent_executions_org_created` for the windowed shape — with no sequential
scan. **Phase 4.4 added no index to `agent_executions`.**

### The honest worst case, and why no index fixes it

One tenant owning the whole table — the shape fragmented development data hides:

| Query | p50 | p95 |
|---|---|---|
| all-rows sum | 20.46 ms | 21.11 ms |
| all-rows grouped by agent | 41.70 ms | 74.39 ms |

That is not an index problem. Summing a tenant's spend requires reading every
row of that tenant's spend; it is O(rows the tenant owns) by definition, unlike
Phase 4.2's list view whose bitmap-plus-sort was O(tenant size) only because it
lacked an ordered path to a `LIMIT`. There is no `LIMIT` to stop at here.

The only thing that makes it sublinear is a **materialized rollup**, which is
the parallel cost store this phase is forbidden to build: two tables claiming
to know what an organization spent, disagreeing after a partial refresh, is a
worse failure than a 40 ms query. If volume ever makes that trade worth taking
it earns its own ADR and its own numbers, the way Phase 4.2's index did.

Until then the bound is the **default 30-day window**. An absent time range
does not mean "everything" — the same discipline as Phase 4.2's explorer.

## Showback, not chargeback

Allocation views exist: spend by project, department, agent, environment.
Nothing bills anyone. Chargeback is future work (§4.4) and raises questions
this phase does not answer — starting with who pays for the bounded overshoot
[ADR-0010](../architecture/adr/0010-budget-reservation-semantics.md) documents.

## Tenant isolation

Every statement leads with `organization_id` and a time range, in that order.
That is both the isolation property and the performance one, which is not a
coincidence: a query that cannot scan another tenant's rows also cannot scan
the whole table. Another tenant's budget is reported as *not found* rather than
forbidden — the existence of a financial record is itself information (§34).

## API

| Method | Path | Permission |
|---|---|---|
| GET | `/api/v1/cost/summary` | `runtime.cost.view` |
| GET | `/api/v1/cost/timeseries` | `runtime.cost.view` |
| GET | `/api/v1/cost/anomalies` | `runtime.cost.view` |
| GET | `/api/v1/cost/executions/{id}/provenance` | `runtime.cost.view` |

`runtime.cost.view` already existed, and its catalog description already read
*"View runtime cost and token usage"* — exactly this capability. Reused rather
than shadowed by a synonym, for the reason Phase 4.2 gave when it declined to
register `runtime.observability.view`.

## See also

- [budgets.md](./budgets.md) — ceilings, modes, reserve-then-reconcile
- [ADR-0010](../architecture/adr/0010-budget-reservation-semantics.md)
- [gateways.md](./gateways.md) — where `cost_amount` is computed (Phase 5.7a.3)
