"""Phase 4.1 - Runtime Telemetry & Trace Context Foundation.

**Two nullable columns, and the restraint is the point.** The obvious shape for
an observability foundation is a span table and an event table. This migration
adds neither, and every omission below is justified rather than deferred --
ACT-SRS-M4 §13 requires proving a table is needed before adding one, and none
of the candidates survived the proof.

**Why there is no ``runtime_trace_spans`` table.** A span describes a model
call, a tool call or an attempt. Every one of those is already a row:
``execution_attempts``, ``execution_messages`` (the assistant turn per loop
iteration) and ``tool_calls``, each carrying its own timings, status, error
class and token accounting, each foreign-keyed to ``agent_executions``. A span
table would be a second, lossy copy of records that are already authoritative,
and the copy is the one that drifts. So spans are *derived*: a span id is a
deterministic UUID5 over (trace id, kind, row id) -- see
``app/observability/trace.py`` -- and a trace is assembled by walking the
foreign keys that already exist (``app/observability/assembly.py``). Nothing is
stored, so nothing can disagree.

**Why there is no new ``runtime_events`` table.** Because there already is one.
``runtime_events`` has existed since the Phase 5.0 runtime schema, with
``event_type``, ``severity``, ``payload``, ``request_id``, ``correlation_id``
and foreign keys to organization/agent/deployment/execution. What it lacked was
a contract and any actual trace identity -- ``correlation_id`` was null on
essentially all ~297,000 rows in this database. 4.1 supplies the contract in
code and starts populating the columns; the storage needed one addition, below.

**Why ``correlation_id`` is not backfilled on ``agent_executions``.** ~74,400
of ~74,600 existing executions have a null ``correlation_id``, so the
temptation is to backfill it from the primary key. That would be a one-way
write of 74,000 rows that ``downgrade()`` could not reverse -- once a synthetic
correlation id is written, nothing distinguishes it from one a caller actually
supplied. Instead the *derivation* does the work:
``trace_id_for(execution)`` returns ``correlation_id or str(execution.id)``, so
every historical execution has a stable, unique trace identity immediately,
with zero rows written and nothing to undo. The fallback is not a degraded
mode: an execution that was never part of a wider caller-defined trace is its
own trace, and its primary key is the right name for it.

The same reasoning removes two other candidate columns:

- **No ``correlation_id`` on ``tool_calls``/``execution_attempts``/
  ``execution_messages``.** All three already carry ``execution_id``. Copying
  the parent's correlation onto each child would denormalize a value reachable
  by one join -- the §13 duplication, arriving as a column instead of a table.
- **No ``correlation_id`` on ``job_runs``.** A scheduled occurrence has no
  caller and therefore no inbound correlation to record. Its trace identity is
  its own row id, derived by ``TraceContext.for_job_run``. A column would only
  ever hold a copy of the primary key.

What is left is the two facts that are genuinely *not* derivable from anything
already stored:

1. ``agent_executions.request_id`` -- the id of the HTTP request that created
   the execution. Distinct from ``correlation_id``: a correlation spans a whole
   caller-defined workflow, a request id names one call within it, and one
   correlation may produce many executions across many requests. It is not
   recoverable from any other column, so if it is not captured here it is lost
   at the end of the request. Indexed, because "show me everything one request
   caused" is the question it exists to answer. Nullable, because every
   execution created before this phase has no request id and inventing one
   would be a lie in a column whose whole value is that it is true.

2. ``runtime_events.span_id`` -- which derived span an event occurred in.
   ``execution_id`` narrows an event to a trace but not to a step within it, so
   this is not derivable either. ``String(64)`` holds the 36-character UUID5
   with room to spare and no room to be abused as a payload field.

**Reversible, and genuinely so.** ``downgrade()`` drops both columns and the
index, restoring the exact pre-4.1 schema. Because nothing is backfilled, a
downgrade loses only data this phase itself created -- there is no pre-existing
column whose values were rewritten and could not be restored.

Revision ID: 0045_runtime_telemetry_context
Revises: 0044_worker_fleet_rolling
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0045_runtime_telemetry_context"
down_revision: str | None = "0044_worker_fleet_rolling"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The HTTP request that created an execution (M4-4.1-FR-002). Nullable:
    # historical rows genuinely have none, and the whole point of the column is
    # that a value in it is true.
    op.add_column(
        "agent_executions",
        sa.Column("request_id", sa.String(length=100), nullable=True),
    )
    op.create_index(
        "ix_agent_executions_request_id", "agent_executions", ["request_id"],
        postgresql_where=sa.text("request_id IS NOT NULL"),
    )

    # Which derived span a telemetry event belongs to (M4-4.1-FR-020).
    # Deliberately not indexed: 4.1 assembles traces from the domain rows and
    # reads events by ``execution_id`` (already indexed). An index sized for a
    # query pattern no code performs is cost without benefit -- 4.2 adds one
    # when it builds the explorer that actually queries this way.
    op.add_column(
        "runtime_events",
        sa.Column("span_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("runtime_events", "span_id")
    op.drop_index("ix_agent_executions_request_id", table_name="agent_executions")
    op.drop_column("agent_executions", "request_id")
