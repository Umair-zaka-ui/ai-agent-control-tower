"""Phase 4.5 - Behavioral Signals & Runtime Anomaly Detection.

One new table. **No new index on `agent_executions` or `tool_calls`**, and that
is a measured conclusion rather than an omission.

## What was measured

Against the live development database at **115,381 executions / 5,210 tool
calls**, busiest agent 500 executions:

    agent-scoped execution window aggregate      0.57ms p50 / 1.42ms p95
    termination-reason breakdown                 0.42ms p50
    per-tool failure breakdown                   0.22ms p50

The interesting part is the plan, not the number. An agent-scoped window filters
on `(organization_id, agent_id, created_at)`, and no composite index covers
that. Postgres does not need one -- it combines the two indexes that already
exist:

    Aggregate
      -> Bitmap Heap Scan on agent_executions   (rows=500, 18 buffers)
        -> BitmapAnd
          -> Bitmap Index Scan on ix_agent_executions_org_created
          -> Bitmap Index Scan on ix_agent_executions_agent

Phase 4.2's tenant+recency index and Milestone 1's `agent_id` index intersect to
answer a query neither was built for. Adding an `(agent_id, created_at)`
composite would buy nothing this measurement can detect, so none is added --
the same restraint Phase 4.4 exercised, with the same obligation to record the
numbers that justify it.

## One shape worth naming rather than fixing on suspicion

`tool_calls` has `ix_tool_calls_agent` on `agent_id` alone, so the window's
`created_at` bound is applied as a post-index **Filter** rather than an index
condition:

    Bitmap Heap Scan on tool_calls
      Recheck Cond: (agent_id = ...)
      Filter: (created_at >= now() - '7 days')

That is the same shape Phase 4.2 found dangerous on `agent_executions`: cheap
while the discriminator selects few rows, O(all rows for that agent) once it
does not. **It cannot be demonstrated here** -- the whole table holds 5,210
rows and the busiest agent has 10, so every variant measures as noise. Adding
an index against a projection rather than a measurement is precisely what
Phases 4.2 and 4.4 refused to do, so none is added, and the trigger is written
down instead:

> **Revisit when any single agent exceeds roughly 50,000 tool calls**, or when
> the per-tool breakdown's p50 passes 10ms. The fix is a
> `(agent_id, created_at)` composite on `tool_calls`, and it should arrive with
> before/after plans the way `0046_trace_explorer_index` did.

## `behavioral_findings`

Findings reference executions through their window bounds; **no execution data
is copied**. The unique constraint on
`(agent_id, signal_type, window_start, window_end)` is the idempotency
primitive, not a performance index: re-running an evaluation over the same
window -- which the Phase 3.8 scheduler will do whenever a run overlaps or
retries -- must produce one finding, and the database enforces that rather than
the application remembering to check first. Same reasoning as Phase 4.4's
partial unique index on budget reservations.

`explanation` and `attribution` are JSONB because both are structured records
whose shape follows the signal: a tool-failure finding names a tool, a latency
drift names a model. A column per field would be a wide table of mostly-nulls,
and a free-text explanation would defeat the phase's entire purpose.

Purely additive, no backfill, reversible.

Revision ID: 0049_behavioral_signals
Revises: 0048_cost_governance
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0049_behavioral_signals"
down_revision = "0048_cost_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "behavioral_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agent_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("environment_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("environments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("signal_type", sa.String(48), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("metric", sa.String(48), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("observed_value", sa.Numeric(18, 6), nullable=True),
        sa.Column("threshold_value", sa.Numeric(18, 6), nullable=True),
        sa.Column("baseline_value", sa.Numeric(18, 6), nullable=True),
        sa.Column("attribution", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("explanation", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        # The five states, constrained at the database because this column is
        # evidence: a row claiming a state the engine cannot produce would be
        # indistinguishable from a real one.
        sa.CheckConstraint(
            "state IN ('NORMAL', 'DEGRADED', 'ANOMALOUS', 'INSUFFICIENT_DATA', 'UNKNOWN')",
            name="ck_behavioral_findings_state"),
        sa.UniqueConstraint("agent_id", "signal_type", "window_start", "window_end",
                            name="uq_behavioral_findings_window"),
    )
    op.create_index("ix_behavioral_findings_agent_evaluated", "behavioral_findings",
                    ["agent_id", "evaluated_at"])
    op.create_index("ix_behavioral_findings_org_evaluated", "behavioral_findings",
                    ["organization_id", "evaluated_at"])


def downgrade() -> None:
    op.drop_index("ix_behavioral_findings_org_evaluated", table_name="behavioral_findings")
    op.drop_index("ix_behavioral_findings_agent_evaluated", table_name="behavioral_findings")
    op.drop_table("behavioral_findings")
