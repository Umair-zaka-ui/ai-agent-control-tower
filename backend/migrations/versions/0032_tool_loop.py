"""Phase 5.6a.3 - Model-Driven Tool Invocation Loop.

Additive only:

1. **`execution_messages`** (new table) — the complete, ordered conversation
   transcript for one execution's model-driven tool loop (`ACT-TLX-FR-049`):
   the initial user input, every assistant turn (final answer or a tool
   request), and every tool result fed back to the next turn. Did not
   pre-exist (checked against the live schema before writing this
   migration, per the build prompt's own instruction to check first).

2. **`agent_executions`** gains two nullable-safe columns: `loop_iterations`
   (INTEGER, default 0 — how many model turns the loop took) and
   `termination_reason` (VARCHAR(40), nullable — COMPLETED/MAX_ITERATIONS/
   TOKEN_BUDGET/WALL_CLOCK/REPEATED_CALL/TOOL_DENIED).

3. **`tool_calls`** gains one nullable column: `loop_iteration` (INTEGER) —
   which model turn a call belongs to; null for a call made through the
   pre-existing explicit `input_payload["tool_calls"]` mechanism.

No column is dropped or retyped.

Revision ID: 0032_tool_loop  (<=32 chars: alembic_version.version_num is varchar(32))
Revises: 0031_tool_resilience
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0032_tool_loop"
down_revision: str | None = "0031_tool_resilience"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- agent_executions: loop accounting ------------------------------
    op.add_column("agent_executions", sa.Column("loop_iterations", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("agent_executions", sa.Column("termination_reason", sa.String(length=40), nullable=True))

    # --- tool_calls: which loop turn a call belongs to ------------------
    op.add_column("tool_calls", sa.Column("loop_iteration", sa.Integer(), nullable=True))

    # --- execution_messages: the full conversation transcript -----------
    op.create_table(
        "execution_messages",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("execution_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("tool_call_id", sa.String(length=100), nullable=True),
        sa.Column("tool_name", sa.String(length=100), nullable=True),
        sa.Column("tool_calls_requested", JSONB(), nullable=True),
        sa.Column("loop_iteration", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_amount", sa.Numeric(18, 8), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["execution_id"], ["agent_executions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_execution_messages_execution_id", "execution_messages", ["execution_id"])


def downgrade() -> None:
    op.drop_index("ix_execution_messages_execution_id", table_name="execution_messages")
    op.drop_table("execution_messages")

    op.drop_column("tool_calls", "loop_iteration")

    op.drop_column("agent_executions", "termination_reason")
    op.drop_column("agent_executions", "loop_iterations")
