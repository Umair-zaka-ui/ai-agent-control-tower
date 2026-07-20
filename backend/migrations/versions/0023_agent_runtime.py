"""Phase 5.0 - Enterprise AI Agent Runtime & Lifecycle Management.

Additive: ``agents`` gains runtime-lifecycle columns (§7.1) — the existing
table (Phase 1/3) stays the one agent registry; nothing is dropped or
retyped.

New tables (§62):

- ``agent_definitions``    behaviour/configuration contract (§7.2)
- ``agent_versions``       immutable, checksummed versions (§7.3, §11)
- ``agent_deployments``    one version deployed to one environment (§7.4)
- ``agent_executions``     runtime invocations; also the execution queue (§30)
- ``execution_attempts``   per-attempt retry history (§31)
- ``execution_locks``      worker claim leases (§32)
- ``capabilities`` / ``agent_capabilities``  capability registry + assignment (§18, §19)
- ``tools`` / ``agent_tools`` / ``tool_calls``  tool registry, assignment, call log (§20, §23, §44)
- ``runtime_events``       lifecycle/health/audit event stream (§51, §76)
- ``deployment_health``    health/heartbeat samples (§49, §50)
- ``idempotency_records``  execution-request dedupe (§33)
- ``runtime_approvals``    human approval obligations raised by the runtime (§39)

Revision ID: 0023_agent_runtime
Revises: 0022_governance_iga
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0023_agent_runtime"
down_revision: str | None = "0022_governance_iga"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- agents: additive runtime-lifecycle columns -----------------------
    op.add_column("agents", sa.Column("slug", sa.String(length=150), nullable=True))
    op.add_column("agents", sa.Column("project_id", sa.UUID(), nullable=True))
    op.add_column("agents", sa.Column("owner_type", sa.String(length=30), nullable=True))
    op.add_column("agents", sa.Column("owner_id", sa.UUID(), nullable=True))
    op.add_column("agents", sa.Column("criticality", sa.String(length=20), nullable=False,
                                       server_default="MEDIUM"))
    op.add_column("agents", sa.Column("data_classification", sa.String(length=30), nullable=False,
                                       server_default="INTERNAL"))
    op.add_column("agents", sa.Column("default_environment", sa.String(length=20), nullable=False,
                                       server_default="DEVELOPMENT"))
    op.add_column("agents", sa.Column("lifecycle_status", sa.String(length=20), nullable=False,
                                       server_default="ACTIVE"))
    op.add_column("agents", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_agents_project", "agents", "projects", ["project_id"], ["id"],
                          ondelete="SET NULL")
    op.create_index("ix_agents_slug", "agents", ["slug"])
    op.create_index("ix_agents_lifecycle_status", "agents", ["lifecycle_status"])

    # --- agent_definitions --------------------------------------------------
    op.create_table(
        "agent_definitions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("framework", sa.String(length=50), nullable=False, server_default="CUSTOM"),
        sa.Column("entrypoint_type", sa.String(length=30), nullable=False, server_default="FUNCTION"),
        sa.Column("entrypoint", sa.String(length=500), nullable=False),
        sa.Column("system_instructions", sa.Text(), nullable=True),
        sa.Column("configuration_schema", JSONB(), nullable=True),
        sa.Column("input_schema", JSONB(), nullable=True),
        sa.Column("output_schema", JSONB(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_definitions_agent", "agent_definitions", ["agent_id"])

    # --- agent_versions -------------------------------------------------------
    op.create_table(
        "agent_versions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("definition_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("semantic_version", sa.String(length=20), nullable=False, server_default="0.1.0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DRAFT"),
        sa.Column("configuration_snapshot", JSONB(), nullable=False, server_default="{}"),
        sa.Column("prompt_snapshot", JSONB(), nullable=True),
        sa.Column("model_configuration", JSONB(), nullable=False, server_default="{}"),
        sa.Column("capabilities_snapshot", JSONB(), nullable=False, server_default="[]"),
        sa.Column("tools_snapshot", JSONB(), nullable=False, server_default="[]"),
        sa.Column("policy_snapshot", JSONB(), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("release_notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["definition_id"], ["agent_definitions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_version"),
    )
    op.create_index("ix_agent_versions_agent", "agent_versions", ["agent_id"])
    op.create_index("ix_agent_versions_status", "agent_versions", ["status"])

    # --- agent_deployments ------------------------------------------------
    op.create_table(
        "agent_deployments",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("agent_version_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("environment", sa.String(length=20), nullable=False, server_default="DEVELOPMENT"),
        sa.Column("deployment_strategy", sa.String(length=20), nullable=False, server_default="RECREATE"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="CREATED"),
        sa.Column("desired_replicas", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active_replicas", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("configuration", JSONB(), nullable=False, server_default="{}"),
        sa.Column("secret_references", JSONB(), nullable=False, server_default="{}"),
        sa.Column("runtime_limits", JSONB(), nullable=False, server_default="{}"),
        sa.Column("health_status", sa.String(length=20), nullable=False, server_default="UNKNOWN"),
        sa.Column("deployed_by", sa.UUID(), nullable=True),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_deployments_agent", "agent_deployments", ["agent_id"])
    op.create_index("ix_agent_deployments_version", "agent_deployments", ["agent_version_id"])
    op.create_index("ix_agent_deployments_org", "agent_deployments", ["organization_id"])
    op.create_index("ix_agent_deployments_status", "agent_deployments", ["status"])

    # --- agent_executions ---------------------------------------------------
    op.create_table(
        "agent_executions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("agent_version_id", sa.UUID(), nullable=False),
        sa.Column("deployment_id", sa.UUID(), nullable=True),
        sa.Column("trigger_type", sa.String(length=20), nullable=False, server_default="API"),
        sa.Column("triggered_by_identity_id", sa.UUID(), nullable=True),
        sa.Column("parent_execution_id", sa.UUID(), nullable=True),
        sa.Column("correlation_id", sa.String(length=100), nullable=True),
        sa.Column("idempotency_key", sa.String(length=150), nullable=True),
        sa.Column("input_payload", JSONB(), nullable=False, server_default="{}"),
        sa.Column("output_payload", JSONB(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="CREATED"),
        sa.Column("decision", sa.String(length=24), nullable=True),
        sa.Column("risk_score", sa.Integer(), nullable=True),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="NORMAL"),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("model_usage", JSONB(), nullable=True),
        sa.Column("tool_usage", JSONB(), nullable=True),
        sa.Column("cost", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["deployment_id"], ["agent_deployments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_execution_id"], ["agent_executions.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_agent_executions_org", "agent_executions", ["organization_id"])
    op.create_index("ix_agent_executions_agent", "agent_executions", ["agent_id"])
    op.create_index("ix_agent_executions_version", "agent_executions", ["agent_version_id"])
    op.create_index("ix_agent_executions_status", "agent_executions", ["status"])
    op.create_index("ix_agent_executions_correlation", "agent_executions", ["correlation_id"])
    op.create_index("ix_agent_executions_idempotency", "agent_executions", ["idempotency_key"])
    # The Postgres-backed queue claim query filters status=QUEUED and orders by
    # priority/queued_at — a composite index keeps that a fast index scan.
    op.create_index("ix_agent_executions_queue", "agent_executions",
                    ["status", "priority", "queued_at"])

    # --- execution_attempts -------------------------------------------------
    op.create_table(
        "execution_attempts",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("execution_id", sa.UUID(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="RUNNING"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["execution_id"], ["agent_executions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_execution_attempts_execution", "execution_attempts", ["execution_id"])

    # --- execution_locks ----------------------------------------------------
    op.create_table(
        "execution_locks",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("execution_id", sa.UUID(), nullable=False),
        sa.Column("worker_id", sa.String(length=100), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["execution_id"], ["agent_executions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("execution_id", name="uq_execution_locks_execution"),
    )

    # --- capabilities / agent_capabilities ----------------------------------
    op.create_table(
        "capabilities",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("risk_level", sa.String(length=20), nullable=False, server_default="MEDIUM"),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("required_permissions", JSONB(), nullable=False, server_default="[]"),
        sa.Column("prohibited_environments", JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_capabilities_name"),
    )

    op.create_table(
        "agent_capabilities",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("agent_version_id", sa.UUID(), nullable=True),
        sa.Column("capability_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="REQUESTED"),
        sa.Column("constraints", JSONB(), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["capability_id"], ["capabilities.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_capabilities_agent", "agent_capabilities", ["agent_id"])
    op.create_index("ix_agent_capabilities_capability", "agent_capabilities", ["capability_id"])
    op.create_index("ix_agent_capabilities_status", "agent_capabilities", ["status"])

    # --- tools / agent_tools / tool_calls ------------------------------------
    op.create_table(
        "tools",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tool_type", sa.String(length=30), nullable=False, server_default="FUNCTION"),
        sa.Column("endpoint_reference", sa.String(length=500), nullable=True),
        sa.Column("input_schema", JSONB(), nullable=True),
        sa.Column("output_schema", JSONB(), nullable=True),
        sa.Column("risk_level", sa.String(length=20), nullable=False, server_default="MEDIUM"),
        sa.Column("side_effect_level", sa.String(length=20), nullable=False, server_default="NONE"),
        sa.Column("data_classification", sa.String(length=30), nullable=False, server_default="INTERNAL"),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_tools_org", "tools", ["organization_id"])

    op.create_table(
        "agent_tools",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("agent_version_id", sa.UUID(), nullable=True),
        sa.Column("tool_id", sa.UUID(), nullable=False),
        sa.Column("allowed_actions", JSONB(), nullable=False, server_default="[]"),
        sa.Column("constraints", JSONB(), nullable=True),
        sa.Column("environment", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="REQUESTED"),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tool_id"], ["tools.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_tools_agent", "agent_tools", ["agent_id"])
    op.create_index("ix_agent_tools_tool", "agent_tools", ["tool_id"])
    op.create_index("ix_agent_tools_status", "agent_tools", ["status"])

    op.create_table(
        "tool_calls",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("execution_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("tool_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("input_summary", JSONB(), nullable=True),
        sa.Column("output_summary", JSONB(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ALLOWED"),
        sa.Column("risk_score", sa.Integer(), nullable=True),
        sa.Column("authorization_decision_id", sa.UUID(), nullable=True),
        sa.Column("approval_id", sa.UUID(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("cost", sa.Numeric(12, 6), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["execution_id"], ["agent_executions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tool_id"], ["tools.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_tool_calls_execution", "tool_calls", ["execution_id"])
    op.create_index("ix_tool_calls_agent", "tool_calls", ["agent_id"])
    op.create_index("ix_tool_calls_tool", "tool_calls", ["tool_id"])

    # --- runtime_events -------------------------------------------------------
    op.create_table(
        "runtime_events",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("deployment_id", sa.UUID(), nullable=True),
        sa.Column("execution_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="INFO"),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("correlation_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["deployment_id"], ["agent_deployments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_id"], ["agent_executions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_runtime_events_org", "runtime_events", ["organization_id"])
    op.create_index("ix_runtime_events_agent", "runtime_events", ["agent_id"])
    op.create_index("ix_runtime_events_execution", "runtime_events", ["execution_id"])
    op.create_index("ix_runtime_events_type", "runtime_events", ["event_type"])

    # --- deployment_health ----------------------------------------------------
    op.create_table(
        "deployment_health",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("deployment_id", sa.UUID(), nullable=False),
        sa.Column("worker_id", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="UNKNOWN"),
        sa.Column("metrics", JSONB(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["deployment_id"], ["agent_deployments.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_deployment_health_deployment", "deployment_health", ["deployment_id"])

    # --- idempotency_records ----------------------------------------------------
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("identity_id", sa.UUID(), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=150), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("execution_id", sa.UUID(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_id"], ["agent_executions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("organization_id", "agent_id", "idempotency_key",
                            name="uq_idempotency_key"),
    )

    # --- runtime_approvals ----------------------------------------------------
    op.create_table(
        "runtime_approvals",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("agent_version_id", sa.UUID(), nullable=True),
        sa.Column("deployment_id", sa.UUID(), nullable=True),
        sa.Column("execution_id", sa.UUID(), nullable=True),
        sa.Column("requested_action", sa.String(length=30), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("matched_policies", JSONB(), nullable=False, server_default="[]"),
        sa.Column("request_summary", JSONB(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["deployment_id"], ["agent_deployments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_id"], ["agent_executions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_runtime_approvals_org", "runtime_approvals", ["organization_id"])
    op.create_index("ix_runtime_approvals_status", "runtime_approvals", ["status"])


def downgrade() -> None:
    op.drop_table("runtime_approvals")
    op.drop_table("idempotency_records")
    op.drop_table("deployment_health")
    op.drop_table("runtime_events")
    op.drop_table("tool_calls")
    op.drop_table("agent_tools")
    op.drop_table("tools")
    op.drop_table("agent_capabilities")
    op.drop_table("capabilities")
    op.drop_table("execution_locks")
    op.drop_table("execution_attempts")
    op.drop_table("agent_executions")
    op.drop_table("agent_deployments")
    op.drop_table("agent_versions")
    op.drop_table("agent_definitions")

    op.drop_index("ix_agents_lifecycle_status", table_name="agents")
    op.drop_index("ix_agents_slug", table_name="agents")
    op.drop_constraint("fk_agents_project", "agents", type_="foreignkey")
    op.drop_column("agents", "archived_at")
    op.drop_column("agents", "lifecycle_status")
    op.drop_column("agents", "default_environment")
    op.drop_column("agents", "data_classification")
    op.drop_column("agents", "criticality")
    op.drop_column("agents", "owner_id")
    op.drop_column("agents", "owner_type")
    op.drop_column("agents", "project_id")
    op.drop_column("agents", "slug")
