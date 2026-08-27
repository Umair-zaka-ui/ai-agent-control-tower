"""Phase 4.2 - Unified AI Execution Trace (Trace Explorer & Timeline).

**One index. No projection, no span table, no materialization of any kind** --
and that restraint is the *measured* outcome ADR-0008 asked this phase to
produce, not an assumption carried forward from 4.1.

**What was measured**, against the live development database at 90,695
executions / 355,377 runtime_events:

- **Trace-detail assembly** (the four-table walk: `agent_executions` +
  `execution_attempts` + `execution_messages` + `tool_calls`) --
  **0.74ms p50, 1.08ms p95**. Every child table already carries an
  `execution_id` index, so the walk is index-backed end to end. A read
  projection would have optimized a query that costs less than a millisecond.
- **Explorer filters**, all six dimensions -- **0.23ms to 0.87ms p50**, none
  seq-scanning `agent_executions`. Even the joins (environment via
  `agent_deployments`, model via the version's `model_configuration` JSONB,
  tool via an `EXISTS` on `tool_calls`) stay sub-millisecond, because the
  tenant predicate narrows first and the joins then run against primary keys.

So no materialization is warranted, and none is added. The numbers are recorded
in `docs/observability/tracing.md` and in ADR-0008's outcome section.

**What the measurement also found, which is why this migration exists at all.**
The development data is fragmented across 62,126 organizations, so the busiest
tenant owns only 500 executions -- which made every tenant-scoped query look
fast for a reason that will not hold for a real customer. Measuring the honest
worst case (one tenant owning the whole table) exposed a genuine cliff:

    all-rows recency LIMIT 50    26.94ms p50 / 142.27ms p95    Parallel Seq Scan

`agent_executions` had **no index on `created_at` at all** -- not standalone,
not composite. The explorer's default query ("this tenant's most recent
executions") therefore planned as a bitmap scan over *every row the tenant
owns*, followed by a top-N sort. At 500 rows that is 0.2ms and invisible. At
500,000 rows it is the whole table.

This index fixes the shape rather than the symptom. Measured before and after,
on the same tenant query:

    BEFORE  Bitmap Heap Scan -> rows=500 -> top-N heapsort   18 buffers, 0.196ms
    AFTER   Index Scan       -> rows=50  -> (no Sort node)    4 buffers, 0.043ms

The Sort node disappearing is the entire point, and it matters far more than the
0.15ms. A bitmap-plus-sort is **O(rows the tenant owns)**; an index scan that
walks in `created_at DESC` order and stops at the LIMIT is **O(limit)** --
independent of tenant size. The explorer stays flat as a tenant grows.

`DESC` is explicit because the index order must match the query's `ORDER BY` for
the sort to be elided; an ascending index would still require a backward scan
and, combined with a filter, could reintroduce the sort.

**This is not a §13 duplication.** It stores no data. It is an index on the
authoritative table, containing only values already in that table's own columns,
maintained by Postgres. Nothing reads it as a source of truth because it is not
a source of anything -- it is an access path to `agent_executions`.

**Why not also index the filter dimensions** (status, environment, model, tool).
Because measurement says they do not need it: with the tenant+recency index
doing the narrowing, every filtered variant lands between 0.24ms and 0.87ms.
Adding a composite per filter combination would be speculative index bloat --
write amplification on the hottest table in the system, paid on every execution
insert, to speed up reads that are already sub-millisecond. If a filter combination
later proves slow at real volume, it gets its own index then, with its own numbers.

Reversible: `downgrade()` drops the index. No data is written or altered in
either direction, so a downgrade loses nothing at all.

Revision ID: 0046_trace_explorer_index
Revises: 0045_runtime_telemetry_context
"""

from __future__ import annotations

from alembic import op

revision: str = "0046_trace_explorer_index"
down_revision: str | None = "0045_runtime_telemetry_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The trace explorer's one hot query shape: a tenant's executions, most
    # recent first, bounded by LIMIT. Leading column is the tenant because
    # every query in this phase is tenant-scoped by construction -- there is no
    # code path that lists executions without an organization predicate.
    op.create_index(
        "ix_agent_executions_org_created",
        "agent_executions",
        ["organization_id", "created_at"],
        postgresql_ops={"created_at": "DESC"},
    )


def downgrade() -> None:
    op.drop_index("ix_agent_executions_org_created", table_name="agent_executions")
