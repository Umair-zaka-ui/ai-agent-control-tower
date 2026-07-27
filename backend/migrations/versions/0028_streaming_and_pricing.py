"""Phase 5.7a.3 - Streaming & Token Accounting.

Three purposes, additive:

1. **Real token/cost accounting on `agent_executions`.** Twelve new
   columns: `prompt_tokens`/`completion_tokens`/`total_tokens` (nullable --
   null means "the provider didn't report usage," never estimated,
   `ACT-MDL-FR-046`), `token_accounting_complete`, `cost_amount`/
   `cost_currency`/`pricing_version`, `cost_is_estimated`,
   `time_to_first_token_ms`/`generation_duration_ms`, `finish_reason`,
   `was_streamed`/`stream_interrupted`. See
   `app/runtime/services.py::ModelGatewayService`/`PricingService` and
   `app/models/runtime.py::AgentExecution` for how these are populated.

2. **Per-attempt token accounting on `execution_attempts`** (`ACT-MDL-FR-
   047`) -- the same three token columns plus `token_accounting_complete`,
   so a retried execution's earlier attempts still show their own usage,
   not only the final one's.

3. **`model_pricing`** (`ACT-MDL-FR-084`) -- provider/model pricing with
   effective dating. A price change is never an UPDATE: it INSERTs a new
   row and closes the prior one's `effective_to`, so a cost already
   computed under an old price stays correct after the price changes (see
   `PricingService.set_price`). Seeded here with a small number of
   illustrative, approximately-dated figures for well-known models behind
   the `OPENAI_COMPATIBLE` adapter -- **these are not live prices** and
   need real operator maintenance; see docs/runtime/providers.md's
   "Pricing seed data" section for exactly what was seeded and why.

**Legacy cost rows** (`ACT-MDL-FR-086`): every `agent_executions` row that
already has a non-zero `cost` predates this migration and was computed by
the flat placeholder formula (`total_tokens * 0.000002`,
`ExecutionWorkerService._execute`, pre-5.7a.3) -- not from real per-model
pricing. This migration marks every such row `cost_is_estimated = true` so
a cost report can never silently conflate a guess with a measurement. It
does **not** recompute or delete any existing `cost` value.

Revision ID: 0028_streaming_and_pricing
Revises: 0027_version_signing
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "0028_streaming_and_pricing"
down_revision: str | None = "0027_version_signing"
branch_labels = None
depends_on = None

# Illustrative seed pricing (ACT-MDL-FR-084) -- approximate, publicly
# documented per-1K-token rates for a handful of well-known models,
# expressed against the "OPENAI_COMPATIBLE" adapter identifier since that
# is the only registered adapter capable of calling them. NOT live prices:
# an operator pointing this adapter at a real metered API must verify and
# maintain these via PricingService.set_price, not by editing this
# migration after the fact. See docs/runtime/providers.md.
_PRICING_VERSION = "2025-01-seed"
_EFFECTIVE_FROM = datetime(2025, 1, 1, tzinfo=timezone.utc)
_SEED_PRICES = [
    # (model_name, prompt_cost_per_1k, completion_cost_per_1k)
    ("gpt-3.5-turbo", "0.00050000", "0.00150000"),
    ("gpt-4o-mini", "0.00015000", "0.00060000"),
    ("gpt-4o", "0.00250000", "0.01000000"),
]


def upgrade() -> None:
    # --- agent_executions: streaming & accounting columns ----------------------
    op.add_column("agent_executions", sa.Column("prompt_tokens", sa.Integer(), nullable=True))
    op.add_column("agent_executions", sa.Column("completion_tokens", sa.Integer(), nullable=True))
    op.add_column("agent_executions", sa.Column("total_tokens", sa.Integer(), nullable=True))
    op.add_column("agent_executions", sa.Column("token_accounting_complete", sa.Boolean(), nullable=False,
                                                server_default=sa.true()))
    op.add_column("agent_executions", sa.Column("cost_amount", sa.Numeric(18, 8), nullable=True))
    op.add_column("agent_executions", sa.Column("cost_currency", sa.String(length=3), nullable=False,
                                                server_default="USD"))
    op.add_column("agent_executions", sa.Column("pricing_version", sa.String(length=32), nullable=True))
    op.add_column("agent_executions", sa.Column("cost_is_estimated", sa.Boolean(), nullable=False,
                                                server_default=sa.false()))
    op.add_column("agent_executions", sa.Column("time_to_first_token_ms", sa.Integer(), nullable=True))
    op.add_column("agent_executions", sa.Column("generation_duration_ms", sa.Integer(), nullable=True))
    op.add_column("agent_executions", sa.Column("finish_reason", sa.String(length=32), nullable=True))
    op.add_column("agent_executions", sa.Column("was_streamed", sa.Boolean(), nullable=False,
                                                server_default=sa.false()))
    op.add_column("agent_executions", sa.Column("stream_interrupted", sa.Boolean(), nullable=False,
                                                server_default=sa.false()))

    # --- Mark legacy placeholder-costed rows (ACT-MDL-FR-086) -------------------
    # Every row with a non-zero cost predates this migration and was
    # computed by the flat total_tokens*0.000002 formula, never a real
    # per-model rate -- not recomputed, only flagged.
    op.execute("UPDATE agent_executions SET cost_is_estimated = true WHERE cost <> 0")

    # --- execution_attempts: per-attempt token accounting (FR-047) -------------
    op.add_column("execution_attempts", sa.Column("prompt_tokens", sa.Integer(), nullable=True))
    op.add_column("execution_attempts", sa.Column("completion_tokens", sa.Integer(), nullable=True))
    op.add_column("execution_attempts", sa.Column("total_tokens", sa.Integer(), nullable=True))
    op.add_column("execution_attempts", sa.Column("token_accounting_complete", sa.Boolean(), nullable=False,
                                                  server_default=sa.true()))

    # --- model_pricing (FR-084) -------------------------------------------------
    op.create_table(
        "model_pricing",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("prompt_cost_per_1k", sa.Numeric(18, 8), nullable=False),
        sa.Column("completion_cost_per_1k", sa.Numeric(18, 8), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("pricing_version", sa.String(length=32), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "model_name", "effective_from", name="uq_model_pricing_provider_model_from"),
    )
    op.create_index("ix_model_pricing_provider", "model_pricing", ["provider"])
    op.create_index("ix_model_pricing_model_name", "model_pricing", ["model_name"])

    model_pricing = sa.table(
        "model_pricing",
        sa.column("id", sa.UUID()),
        sa.column("provider", sa.String()),
        sa.column("model_name", sa.String()),
        sa.column("prompt_cost_per_1k", sa.Numeric()),
        sa.column("completion_cost_per_1k", sa.Numeric()),
        sa.column("currency", sa.String()),
        sa.column("pricing_version", sa.String()),
        sa.column("effective_from", sa.DateTime()),
    )
    op.bulk_insert(model_pricing, [
        {
            "id": uuid.uuid4(), "provider": "OPENAI_COMPATIBLE", "model_name": model_name,
            "prompt_cost_per_1k": prompt_cost, "completion_cost_per_1k": completion_cost,
            "currency": "USD", "pricing_version": _PRICING_VERSION, "effective_from": _EFFECTIVE_FROM,
        }
        for model_name, prompt_cost, completion_cost in _SEED_PRICES
    ])


def downgrade() -> None:
    op.drop_index("ix_model_pricing_model_name", table_name="model_pricing")
    op.drop_index("ix_model_pricing_provider", table_name="model_pricing")
    op.drop_table("model_pricing")

    op.drop_column("execution_attempts", "token_accounting_complete")
    op.drop_column("execution_attempts", "total_tokens")
    op.drop_column("execution_attempts", "completion_tokens")
    op.drop_column("execution_attempts", "prompt_tokens")

    op.drop_column("agent_executions", "stream_interrupted")
    op.drop_column("agent_executions", "was_streamed")
    op.drop_column("agent_executions", "finish_reason")
    op.drop_column("agent_executions", "generation_duration_ms")
    op.drop_column("agent_executions", "time_to_first_token_ms")
    op.drop_column("agent_executions", "cost_is_estimated")
    op.drop_column("agent_executions", "pricing_version")
    op.drop_column("agent_executions", "cost_currency")
    op.drop_column("agent_executions", "cost_amount")
    op.drop_column("agent_executions", "token_accounting_complete")
    op.drop_column("agent_executions", "total_tokens")
    op.drop_column("agent_executions", "completion_tokens")
    op.drop_column("agent_executions", "prompt_tokens")
