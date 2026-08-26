"""Phase 4.3 - Runtime Governance Enforcement Engine.

Two tables, and the division between them is the point.

**``runtime_governance_policies``** -- the configurable rules, scoped
organization / environment / agent with most-specific-wins resolution, exactly
the shape ``rollback_trigger_policies`` (migration 0042) already established
for the same kind of question. ``constraints`` is JSONB rather than a column
per rule for the same reason ``environments.policy`` and
``rollback_trigger_policies.thresholds`` are: a new governed limit should not
need a migration. Keys are validated on write against a known set, so a typo
is rejected rather than stored as a control that silently never fires.

``organization_id`` is nullable, and null means *platform default*. No
tenant-facing API path can write one -- ``GovernancePolicyService.create``
always stamps the actor's own organization -- because a row with a null
organization governs every tenant on the platform, and no per-tenant
permission should reach that far. The column exists so a platform operator can
seed a floor through a migration or an admin path later; it is not a hole in
tenant isolation.

**``runtime_governance_decisions``** -- append-only lineage, one row per
material decision. This is the answer to *"why did this execution stop"*.

It complements ``agent_executions.termination_reason`` rather than duplicating
it, and the split is deliberate. The execution row records the terminal state
the execution *reached*, which is a property of the execution and stays where
every existing reader already looks for it. This table records which
checkpoint decided, under which policy, with what obligation -- of which one
execution may produce several (a denied tool call, then a stop). A single
column cannot hold a sequence, and one that sometimes meant "hit the iteration
cap" and sometimes "policy 7f3a denied gpt-4o at AFTER_MODEL_RESPONSE" would
serve neither reader.

**Append-only is enforced at the database, not only by convention.** No
service method updates or deletes a row here, and this migration additionally
revokes UPDATE and DELETE from every non-owner role -- the same belt-and-braces
``deployment_events`` (0037) uses. A governance decision that could be edited
after the fact is not evidence of anything.

**What this migration does not add.** No column on ``agent_executions``. The
engine reads cost, tokens, timings and status from the columns that already
exist (M4-4.3-FR-011 -- budgets and reservations are Phase 4.4's), and writes
its own record here. The execution path gains an engine, not a schema change.

Revision ID: 0047_runtime_governance
Revises: 0046_trace_explorer_index
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0047_runtime_governance"
down_revision = "0046_trace_explorer_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_governance_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("environment_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("environments.id", ondelete="CASCADE"), nullable=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("constraints", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("mandatory", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # The resolution query filters on all three scope columns at once, so one
    # composite index serves it rather than three single-column ones.
    op.create_index("ix_runtime_governance_policies_scope", "runtime_governance_policies",
                    ["organization_id", "environment_id", "agent_id"])

    op.create_table(
        "runtime_governance_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agent_executions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("trace_id", sa.String(100), nullable=True, index=True),
        sa.Column("checkpoint", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(12), nullable=False),
        sa.Column("reason_code", sa.String(48), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("obligation", postgresql.JSONB(), nullable=True),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("runtime_governance_policies.id", ondelete="SET NULL"), nullable=True),
        sa.Column("iteration", sa.Integer(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        # A decision is one of four values and a checkpoint one of six. Both
        # are constrained here rather than trusted from the application,
        # because this table is evidence: a row claiming a decision the engine
        # cannot produce would be indistinguishable from a real one.
        sa.CheckConstraint("decision IN ('ALLOW', 'DENY', 'CHALLENGE', 'STOP')",
                           name="ck_runtime_governance_decisions_decision"),
        sa.CheckConstraint(
            "checkpoint IN ('BEFORE_FIRST_MODEL_CALL', 'AFTER_MODEL_RESPONSE', "
            "'BEFORE_TOOL_EXECUTION', 'AFTER_TOOL_EXECUTION', 'BEFORE_NEXT_ITERATION', "
            "'BEFORE_FINAL_OUTPUT')",
            name="ck_runtime_governance_decisions_checkpoint"),
    )
    op.create_index("ix_runtime_governance_decisions_execution", "runtime_governance_decisions",
                    ["execution_id", "evaluated_at"])

    # Append-only at the database level (M4-4.3-FR-040). PUBLIC covers every
    # role that is not the table's owner; the owner remains able to run a
    # future migration against it, which is the one legitimate reason to touch
    # these rows.
    op.execute("REVOKE UPDATE, DELETE ON runtime_governance_decisions FROM PUBLIC")


def downgrade() -> None:
    op.drop_index("ix_runtime_governance_decisions_execution",
                  table_name="runtime_governance_decisions")
    op.drop_table("runtime_governance_decisions")
    op.drop_index("ix_runtime_governance_policies_scope",
                  table_name="runtime_governance_policies")
    op.drop_table("runtime_governance_policies")
