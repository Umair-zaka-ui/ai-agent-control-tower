"""Phase 4.4 - Enterprise AI Cost Governance & FinOps.

Two new tables and one nullable column. **No new index on `agent_executions`,
and no cost is copied anywhere** -- both of those are measured conclusions, not
assumptions carried forward.

## What was measured

Against the live development database at **109,398 executions** (8,627 of them
priced) spread over 10,934 tenants, busiest tenant 500 rows:

    summary, 30-day window, no breakdown         0.80ms p50 / 0.91ms p95
    summary by agent / model / provider          1.99 - 2.30ms p50
    summary by environment (deployment join)     5.69ms p50
    timeseries (daily buckets, date_trunc)       1.11ms p50
    anomaly scan over that series                1.04ms p50

Every one of them reaches its rows through an existing index -- Phase 4.2's
`ix_agent_executions_org_created` for the windowed shape, `ix_agent_executions_org`
for the unwindowed one. No sequential scan anywhere:

    Aggregate
      -> Bitmap Heap Scan on agent_executions   (rows=500, 15 buffers)
        -> Bitmap Index Scan on ix_agent_executions_org_created

So the tenant-scoped read path needs nothing from this migration.

## The honest worst case, and why no index fixes it

Measuring "one tenant owns the whole table" -- the shape the fragmented
development data hides, and the one Phase 4.2 was caught out by -- gives:

    all-rows sum                    20.46ms p50
    all-rows grouped by agent       41.70ms p50 / 74.39ms p95

That is not an index problem and **no index can make it one**. Summing a
tenant's spend requires reading every row of that tenant's spend; the work is
O(rows the tenant owns) by definition, unlike Phase 4.2's list view, whose
bitmap-plus-sort was O(tenant size) only because it lacked an ordered path to
a LIMIT. There is no LIMIT to stop at here.

The only thing that would make it sublinear is a **materialized rollup** -- and
that is precisely the parallel cost store this phase is forbidden to build.
Two tables claiming to know what an organization spent, disagreeing after a
partial refresh, is a worse failure than a 40ms query. If a tenant's volume
ever makes that trade worth taking, it earns its own ADR and its own numbers,
the way Phase 4.2's index did. Until then the default 30-day window is the
bound, and it is an honest one: an absent time range does not mean "everything".

## `budgets`

Holds a limit and a mode. **It holds no cost.** Real per-execution cost stays
on `agent_executions.cost_amount` with its `pricing_version` provenance, where
it was written inside the transaction that made it true.

`scope_id` is deliberately **not** a foreign key: it addresses agents,
projects and environments depending on `scope_type`, and a MODEL-scoped budget
names a model identifier that is a string rather than a row anywhere -- which
is what `scope_value` carries.

`reservation_estimate` is the one column beyond the SRS's sketch. Reserve-then-
reconcile has to hold something before an execution runs, and a model call's
cost is unknowable until it returns, so how much to hold is a budget owner's
decision and is not derivable from anything else.

## `budget_reservations`

The concurrency core. Three indexes, each with a job:

- `ix_budget_reservations_period` (budget, period_key, status) serves the
  remaining-balance sum, which is read *inside* the `FOR UPDATE` that
  serializes claims -- so it is on the hot path of every reservation and is the
  reason that lock is held for microseconds rather than milliseconds.
- `ix_budget_reservations_execution` serves reconcile and release, which look
  up by execution.
- `uq_budget_reservations_live` is not a performance index at all. It is the
  **idempotency primitive**: a partial UNIQUE on (budget_id, execution_id)
  WHERE status <> 'RELEASED' means one execution can hold at most one live
  reservation against one budget, enforced by Postgres rather than promised by
  the application. A RELEASED row does not participate, which is what lets a
  retried attempt claim afresh -- and is why orphan release is a correctness
  requirement rather than housekeeping.

  Same reasoning as Phase 3.1's `idempotency_keys` unique constraint (the
  constraint *is* the concurrency primitive), reached without its
  claim-then-poll machinery because a reservation has a natural key and no
  result to wait for.

## `runtime_governance_decisions.budget_id`

One nullable column on Phase 4.3's decision lineage. A budget-driven STOP has
no governance *policy* behind it -- a budget is not a row in
`runtime_governance_policies` -- so without this the lineage could record that
a decision was made for `BUDGET_EXCEEDED` but not which ceiling made it. A
decision carries at most one of `policy_id` / `budget_id`.

Purely additive, no backfill, reversible.

Revision ID: 0048_cost_governance
Revises: 0047_runtime_governance
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0048_cost_governance"
down_revision = "0047_runtime_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "budgets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scope_type", sa.String(16), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope_value", sa.String(128), nullable=True),
        sa.Column("mode", sa.String(20), nullable=False, server_default="INFORMATIONAL"),
        sa.Column("period", sa.String(16), nullable=False, server_default="MONTHLY"),
        sa.Column("limit_amount", sa.Numeric(18, 8), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("reservation_estimate", sa.Numeric(18, 8), nullable=True),
        sa.Column("threshold_percent", sa.Integer(), nullable=False, server_default="80"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "scope_type IN ('ORGANIZATION', 'PROJECT', 'AGENT', 'ENVIRONMENT', 'MODEL')",
            name="ck_budgets_scope_type"),
        sa.CheckConstraint(
            "mode IN ('INFORMATIONAL', 'WARNING', 'HARD_LIMIT', 'APPROVAL_REQUIRED')",
            name="ck_budgets_mode"),
        sa.CheckConstraint("period IN ('DAILY', 'MONTHLY', 'EXECUTION')",
                           name="ck_budgets_period"),
        sa.CheckConstraint("limit_amount >= 0", name="ck_budgets_limit_non_negative"),
    )
    op.create_index("ix_budgets_scope", "budgets",
                    ["organization_id", "scope_type", "scope_id", "enabled"])

    op.create_table(
        "budget_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("budget_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agent_executions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("reserved_amount", sa.Numeric(18, 8), nullable=False),
        sa.Column("actual_amount", sa.Numeric(18, 8), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="RESERVED"),
        sa.Column("period_key", sa.String(64), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('RESERVED', 'RECONCILED', 'RELEASED')",
                           name="ck_budget_reservations_status"),
        sa.CheckConstraint("reserved_amount >= 0", name="ck_budget_reservations_amount"),
    )
    op.create_index("ix_budget_reservations_period", "budget_reservations",
                    ["budget_id", "period_key", "status"])
    op.create_index("ix_budget_reservations_execution", "budget_reservations",
                    ["execution_id"])
    op.create_index("uq_budget_reservations_live", "budget_reservations",
                    ["budget_id", "execution_id"], unique=True,
                    postgresql_where=sa.text("status <> 'RELEASED'"))

    op.add_column("runtime_governance_decisions",
                  sa.Column("budget_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_runtime_governance_decisions_budget",
                          "runtime_governance_decisions", "budgets",
                          ["budget_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_runtime_governance_decisions_budget",
                       "runtime_governance_decisions", type_="foreignkey")
    op.drop_column("runtime_governance_decisions", "budget_id")
    op.drop_index("uq_budget_reservations_live", table_name="budget_reservations")
    op.drop_index("ix_budget_reservations_execution", table_name="budget_reservations")
    op.drop_index("ix_budget_reservations_period", table_name="budget_reservations")
    op.drop_table("budget_reservations")
    op.drop_index("ix_budgets_scope", table_name="budgets")
    op.drop_table("budgets")
