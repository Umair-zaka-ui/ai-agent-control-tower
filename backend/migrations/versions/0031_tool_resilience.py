"""Phase 5.6a.2 - Tool Schema Validation & Resilience.

Additive only: three new nullable columns on `tool_calls`, none of which
pre-existed (checked against 0030_http_tool_egress and the live model
before writing this migration, per the build prompt's own instruction to
check first).

- `error_class` (VARCHAR(32)) -- the same `ProviderErrorClass` taxonomy
  Phase 5.7a.4 built for model-provider failures (ACT-MDL-FR-060), reused
  unchanged for a tool's HTTP-level failure (AC-12): RATE_LIMITED,
  PROVIDER_UNAVAILABLE, TIMEOUT, AUTHENTICATION_FAILED, INVALID_REQUEST,
  UNKNOWN. Null for a call that never reached classification (DENIED,
  ALLOWED with no failure, FUNCTION/echo).
- `attempt_number` (INTEGER) -- which retry attempt this row represents
  (1 for a call's first/only attempt; a retried idempotent call gets a
  second `ToolCall` row with attempt_number=2, and so on).
- `validation_error` (TEXT) -- the structured (JSON-encoded) input/output
  schema-validation violation, when `error_code = 'TOOL_SCHEMA_INVALID'`.

No column is dropped or retyped.

Revision ID: 0031_tool_resilience  (<=32 chars: alembic_version.version_num is varchar(32))
Revises: 0030_http_tool_egress
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0031_tool_resilience"
down_revision: str | None = "0030_http_tool_egress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tool_calls", sa.Column("error_class", sa.String(length=32), nullable=True))
    op.add_column("tool_calls", sa.Column("attempt_number", sa.Integer(), nullable=True))
    op.add_column("tool_calls", sa.Column("validation_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tool_calls", "validation_error")
    op.drop_column("tool_calls", "attempt_number")
    op.drop_column("tool_calls", "error_class")
