"""Phase 5.1 - Enterprise Agent Registry, Definitions & Lifecycle.

Additive, same philosophy as 0023: ``agents``/``agent_definitions`` gain the
richer registry columns (ownership, org-hierarchy scoping, machine identity,
classification, tags/metadata, optimistic concurrency) rather than forking a
second registry table. ``agent_identities`` gains the one-identity-per-agent
constraint the SRS's mandatory machine-identity model assumes but which
Phase 5.0 never enforced.

New tables (SRS §46):

- ``agent_ownership_history``  immutable ownership-change ledger (§13)
- ``agent_lifecycle_events``   structured lifecycle transition ledger (§21)
- ``agent_validation_runs``    validation-report engine output (§26)
- ``agent_duplicate_matches``  exact/similarity duplicate detection (§33)
- ``agent_import_jobs`` / ``agent_import_items``  import job tracking (§45)
- ``agent_export_jobs``        export job tracking (§45); the exported
  payload is stored inline on the row (``payload``) since this environment
  has no object-storage service to hand ``storage_reference`` off to.
- ``agent_migration_records``  legacy-agent classification audit (§73)

Revision ID: 0024_agent_registry
Revises: 0023_agent_runtime
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0024_agent_registry"
down_revision: str | None = "0023_agent_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- agents: additive registry columns (§6.1) --------------------------
    op.add_column("agents", sa.Column("business_unit_id", sa.UUID(), nullable=True))
    op.add_column("agents", sa.Column("department_id", sa.UUID(), nullable=True))
    op.add_column("agents", sa.Column("team_id", sa.UUID(), nullable=True))
    op.add_column("agents", sa.Column("identity_id", sa.UUID(), nullable=True))
    op.add_column("agents", sa.Column("display_name", sa.String(length=255), nullable=True))
    op.add_column("agents", sa.Column("business_purpose", sa.Text(), nullable=True))
    # NOTE: ``risk_level`` already exists (0003_agent_management, LOW/MEDIUM/
    # HIGH/CRITICAL, actively used by the legacy /agents module) — SRS §15's
    # declared risk classification reuses that column rather than forking a
    # second one; "MODERATE" in the SRS maps onto the existing "MEDIUM" value.
    # It just gets the index it never had.
    op.add_column("agents", sa.Column("autonomy_level", sa.String(length=30), nullable=False,
                                       server_default="ASSISTIVE"))
    op.add_column("agents", sa.Column("technical_owner_id", sa.UUID(), nullable=True))
    op.add_column("agents", sa.Column("compliance_owner_id", sa.UUID(), nullable=True))
    op.add_column("agents", sa.Column("support_contact", sa.String(length=255), nullable=True))
    op.add_column("agents", sa.Column("documentation_url", sa.String(length=500), nullable=True))
    op.add_column("agents", sa.Column("repository_url", sa.String(length=500), nullable=True))
    op.add_column("agents", sa.Column("tags", JSONB(), nullable=False, server_default="[]"))
    op.add_column("agents", sa.Column("metadata", JSONB(), nullable=False, server_default="{}"))
    op.add_column("agents", sa.Column("registration_source", sa.String(length=30), nullable=False,
                                       server_default="MANUAL"))
    op.add_column("agents", sa.Column("external_reference", sa.String(length=255), nullable=True))
    op.add_column("agents", sa.Column("created_by", sa.UUID(), nullable=True))
    op.add_column("agents", sa.Column("updated_by", sa.UUID(), nullable=True))
    op.add_column("agents", sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agents", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agents", sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agents", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agents", sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agents", sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"))

    op.create_foreign_key("fk_agents_business_unit", "agents", "business_units",
                          ["business_unit_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_agents_department", "agents", "departments",
                          ["department_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_agents_team", "agents", "teams",
                          ["team_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_agents_identity", "agents", "agent_identities",
                          ["identity_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_agents_technical_owner", "agents", "users",
                          ["technical_owner_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_agents_compliance_owner", "agents", "users",
                          ["compliance_owner_id"], ["id"], ondelete="SET NULL")

    op.create_unique_constraint("uq_agents_org_slug", "agents", ["organization_id", "slug"])
    op.create_unique_constraint("uq_agents_org_external_ref", "agents",
                                ["organization_id", "external_reference"])

    op.create_index("ix_agents_business_unit", "agents", ["business_unit_id"])
    op.create_index("ix_agents_department", "agents", ["department_id"])
    op.create_index("ix_agents_team", "agents", ["team_id"])
    op.create_index("ix_agents_identity", "agents", ["identity_id"])
    op.create_index("ix_agents_project", "agents", ["project_id"])
    op.create_index("ix_agents_owner", "agents", ["owner_id"])
    op.create_index("ix_agents_criticality", "agents", ["criticality"])
    op.create_index("ix_agents_risk_level", "agents", ["risk_level"])
    op.create_index("ix_agents_autonomy_level", "agents", ["autonomy_level"])
    op.create_index("ix_agents_data_classification", "agents", ["data_classification"])
    op.create_index("ix_agents_created_at", "agents", ["created_at"])
    op.create_index("ix_agents_updated_at", "agents", ["updated_at"])
    op.create_index("ix_agents_tags_gin", "agents", ["tags"], postgresql_using="gin")
    op.create_index("ix_agents_metadata_gin", "agents", ["metadata"], postgresql_using="gin")
    op.execute(
        "CREATE INDEX ix_agents_fulltext ON agents USING gin ("
        "to_tsvector('english', coalesce(name, '') || ' ' || coalesce(description, '') "
        "|| ' ' || coalesce(business_purpose, '')))"
    )

    # --- agent_definitions: additive contract/requirement columns (§7) -----
    op.add_column("agent_definitions", sa.Column("framework_version", sa.String(length=50), nullable=True))
    op.add_column("agent_definitions", sa.Column("runtime_language", sa.String(length=50), nullable=True))
    op.add_column("agent_definitions", sa.Column("capability_declarations", JSONB(), nullable=False,
                                                  server_default="[]"))
    op.add_column("agent_definitions", sa.Column("tool_declarations", JSONB(), nullable=False,
                                                  server_default="[]"))
    op.add_column("agent_definitions", sa.Column("model_requirements", JSONB(), nullable=False,
                                                  server_default="{}"))
    op.add_column("agent_definitions", sa.Column("memory_requirements", JSONB(), nullable=False,
                                                  server_default="{}"))
    op.add_column("agent_definitions", sa.Column("data_requirements", JSONB(), nullable=False,
                                                  server_default="{}"))
    op.add_column("agent_definitions", sa.Column("network_requirements", JSONB(), nullable=False,
                                                  server_default="{}"))
    op.add_column("agent_definitions", sa.Column("secret_requirements", JSONB(), nullable=False,
                                                  server_default="{}"))
    op.add_column("agent_definitions", sa.Column("runtime_requirements", JSONB(), nullable=False,
                                                  server_default="{}"))
    op.add_column("agent_definitions", sa.Column("created_by", sa.UUID(), nullable=True))
    op.add_column("agent_definitions", sa.Column("updated_by", sa.UUID(), nullable=True))
    op.add_column("agent_definitions", sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(),
    ))

    # --- agent_identities: one identity per agent (§11.1) -------------------
    op.create_unique_constraint("uq_agent_identities_agent", "agent_identities", ["agent_id"])

    # --- agent_ownership_history (§13) --------------------------------------
    op.create_table(
        "agent_ownership_history",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("owner_role", sa.String(length=30), nullable=False),
        sa.Column("previous_owner_type", sa.String(length=30), nullable=True),
        sa.Column("previous_owner_id", sa.UUID(), nullable=True),
        sa.Column("new_owner_type", sa.String(length=30), nullable=False),
        sa.Column("new_owner_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.UUID(), nullable=False),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_ownership_history_agent", "agent_ownership_history", ["agent_id"])

    # --- agent_lifecycle_events (§21) ---------------------------------------
    op.create_table(
        "agent_lifecycle_events",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("previous_status", sa.String(length=20), nullable=True),
        sa.Column("new_status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.UUID(), nullable=False),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("authorization_decision_id", sa.UUID(), nullable=True),
        sa.Column("request_id", sa.String(length=100), nullable=False),
        sa.Column("correlation_id", sa.String(length=100), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_lifecycle_events_agent", "agent_lifecycle_events", ["agent_id"])
    op.create_index("ix_agent_lifecycle_events_org", "agent_lifecycle_events", ["organization_id"])

    # --- agent_validation_runs (§26) ----------------------------------------
    op.create_table(
        "agent_validation_runs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="RUNNING"),
        sa.Column("validator_version", sa.String(length=20), nullable=False),
        sa.Column("summary", JSONB(), nullable=False, server_default="{}"),
        sa.Column("errors", JSONB(), nullable=False, server_default="[]"),
        sa.Column("warnings", JSONB(), nullable=False, server_default="[]"),
        sa.Column("checks", JSONB(), nullable=False, server_default="[]"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_validation_runs_agent", "agent_validation_runs", ["agent_id"])

    # --- agent_duplicate_matches (§33) --------------------------------------
    op.create_table(
        "agent_duplicate_matches",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("source_agent_id", sa.UUID(), nullable=False),
        sa.Column("candidate_agent_id", sa.UUID(), nullable=False),
        sa.Column("match_type", sa.String(length=20), nullable=False),
        sa.Column("confidence_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("matching_fields", JSONB(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="POSSIBLE_DUPLICATE"),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("review_decision", sa.String(length=30), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_agent_id"], ["agents.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_duplicate_matches_source", "agent_duplicate_matches", ["source_agent_id"])
    op.create_index("ix_agent_duplicate_matches_candidate", "agent_duplicate_matches", ["candidate_agent_id"])
    op.create_index("ix_agent_duplicate_matches_status", "agent_duplicate_matches", ["status"])

    # --- agent_import_jobs / agent_import_items (§45) -----------------------
    op.create_table(
        "agent_import_jobs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("format", sa.String(length=10), nullable=False),
        sa.Column("mode", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("total_records", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successful_records", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_records", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_records", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_import_jobs_org", "agent_import_jobs", ["organization_id"])

    op.create_table(
        "agent_import_items",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("import_job_id", sa.UUID(), nullable=False),
        sa.Column("record_identifier", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("errors", JSONB(), nullable=False, server_default="[]"),
        sa.Column("warnings", JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["import_job_id"], ["agent_import_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_agent_import_items_job", "agent_import_items", ["import_job_id"])

    # --- agent_export_jobs (§45) --------------------------------------------
    op.create_table(
        "agent_export_jobs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("export_type", sa.String(length=30), nullable=False),
        sa.Column("format", sa.String(length=10), nullable=False),
        sa.Column("filters", JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("record_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_reference", sa.String(length=500), nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_export_jobs_org", "agent_export_jobs", ["organization_id"])

    # --- agent_migration_records (§73) --------------------------------------
    op.create_table(
        "agent_migration_records",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("migration_batch_id", sa.String(length=100), nullable=False),
        sa.Column("legacy_source", sa.String(length=100), nullable=False),
        sa.Column("legacy_id", sa.String(length=100), nullable=False),
        sa.Column("migration_status", sa.String(length=30), nullable=False),
        sa.Column("mapping_warnings", JSONB(), nullable=False, server_default="[]"),
        sa.Column("migrated_by", sa.UUID(), nullable=True),
        sa.Column("migrated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_migration_records_agent", "agent_migration_records", ["agent_id"])
    op.create_index("ix_agent_migration_records_batch", "agent_migration_records", ["migration_batch_id"])


def downgrade() -> None:
    op.drop_table("agent_migration_records")
    op.drop_table("agent_export_jobs")
    op.drop_table("agent_import_items")
    op.drop_table("agent_import_jobs")
    op.drop_table("agent_duplicate_matches")
    op.drop_table("agent_validation_runs")
    op.drop_table("agent_lifecycle_events")
    op.drop_table("agent_ownership_history")

    op.drop_constraint("uq_agent_identities_agent", "agent_identities", type_="unique")

    op.drop_column("agent_definitions", "updated_at")
    op.drop_column("agent_definitions", "updated_by")
    op.drop_column("agent_definitions", "created_by")
    op.drop_column("agent_definitions", "runtime_requirements")
    op.drop_column("agent_definitions", "secret_requirements")
    op.drop_column("agent_definitions", "network_requirements")
    op.drop_column("agent_definitions", "data_requirements")
    op.drop_column("agent_definitions", "memory_requirements")
    op.drop_column("agent_definitions", "model_requirements")
    op.drop_column("agent_definitions", "tool_declarations")
    op.drop_column("agent_definitions", "capability_declarations")
    op.drop_column("agent_definitions", "runtime_language")
    op.drop_column("agent_definitions", "framework_version")

    op.execute("DROP INDEX IF EXISTS ix_agents_fulltext")
    op.drop_index("ix_agents_metadata_gin", table_name="agents")
    op.drop_index("ix_agents_tags_gin", table_name="agents")
    op.drop_index("ix_agents_updated_at", table_name="agents")
    op.drop_index("ix_agents_created_at", table_name="agents")
    op.drop_index("ix_agents_data_classification", table_name="agents")
    op.drop_index("ix_agents_autonomy_level", table_name="agents")
    op.drop_index("ix_agents_risk_level", table_name="agents")
    op.drop_index("ix_agents_criticality", table_name="agents")
    op.drop_index("ix_agents_owner", table_name="agents")
    op.drop_index("ix_agents_project", table_name="agents")
    op.drop_index("ix_agents_identity", table_name="agents")
    op.drop_index("ix_agents_team", table_name="agents")
    op.drop_index("ix_agents_department", table_name="agents")
    op.drop_index("ix_agents_business_unit", table_name="agents")

    op.drop_constraint("uq_agents_org_external_ref", "agents", type_="unique")
    op.drop_constraint("uq_agents_org_slug", "agents", type_="unique")

    op.drop_constraint("fk_agents_compliance_owner", "agents", type_="foreignkey")
    op.drop_constraint("fk_agents_technical_owner", "agents", type_="foreignkey")
    op.drop_constraint("fk_agents_identity", "agents", type_="foreignkey")
    op.drop_constraint("fk_agents_team", "agents", type_="foreignkey")
    op.drop_constraint("fk_agents_department", "agents", type_="foreignkey")
    op.drop_constraint("fk_agents_business_unit", "agents", type_="foreignkey")

    op.drop_column("agents", "row_version")
    op.drop_column("agents", "retired_at")
    op.drop_column("agents", "suspended_at")
    op.drop_column("agents", "activated_at")
    op.drop_column("agents", "approved_at")
    op.drop_column("agents", "validated_at")
    op.drop_column("agents", "updated_by")
    op.drop_column("agents", "created_by")
    op.drop_column("agents", "external_reference")
    op.drop_column("agents", "registration_source")
    op.drop_column("agents", "metadata")
    op.drop_column("agents", "tags")
    op.drop_column("agents", "repository_url")
    op.drop_column("agents", "documentation_url")
    op.drop_column("agents", "support_contact")
    op.drop_column("agents", "compliance_owner_id")
    op.drop_column("agents", "technical_owner_id")
    op.drop_column("agents", "autonomy_level")
    op.drop_column("agents", "business_purpose")
    op.drop_column("agents", "display_name")
    op.drop_column("agents", "identity_id")
    op.drop_column("agents", "team_id")
    op.drop_column("agents", "department_id")
    op.drop_column("agents", "business_unit_id")
