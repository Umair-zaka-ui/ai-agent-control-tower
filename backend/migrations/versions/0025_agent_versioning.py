"""Phase 5.2 Part 1 - Enterprise Immutable Agent Versioning & Release Management.

Additive, same philosophy as 0023/0024: ``agent_versions`` (Phase 5.0) gains
the release-management columns this foundation needs (lineage pointers,
release channel, compatibility/signature placeholders, retirement) rather
than forking a second version table. Six new satellite tables hold the
one-to-one and one-to-many release data that doesn't belong on the version
row itself:

- ``agent_release_channels``   global release-channel catalog (§9 scope
  bullet "release channels"), seeded with STABLE/BETA/CANARY/INTERNAL.
- ``agent_version_snapshots``  the frozen, immutable snapshot blob (§10-14)
  — the version row keeps its existing per-field JSONB snapshots
  (``configuration_snapshot`` etc., Phase 5.0's checksum surface); this
  table holds the *complete* frozen structure (registry + definition +
  release metadata + everything) as one document, per §13's "Snapshot
  Sections".
- ``agent_release_metadata``   release naming/justification/window fields
  (§26, §28) — one row per version.
- ``agent_release_artifacts``  artifact references (§27) — many per version.
- ``agent_release_notes``      structured, categorized release notes (§28)
  — many per version; distinct from the existing free-text
  ``agent_versions.release_notes`` summary field.
- ``agent_version_status_history``  lifecycle transition ledger (§19, §25)
  — mirrors ``agent_lifecycle_events`` from 0024.

Revision ID: 0025_agent_versioning
Revises: 0024_agent_registry
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0025_agent_versioning"
down_revision: str | None = "0024_agent_registry"
branch_labels = None
depends_on = None

_DEFAULT_CHANNELS = [
    ("STABLE", "Generally available releases.", True),
    ("BETA", "Pre-release, opt-in testing.", False),
    ("CANARY", "Early-access, small-blast-radius rollout.", False),
    ("INTERNAL", "Internal-only, never customer-facing.", False),
]


def upgrade() -> None:
    # --- agent_release_channels (§9, §26) -----------------------------------
    channels = op.create_table(
        "agent_release_channels",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("name", sa.String(length=30), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.bulk_insert(
        channels,
        [
            {"id": uuid.uuid4(), "name": name, "description": description, "is_default": is_default}
            for name, description, is_default in _DEFAULT_CHANNELS
        ],
    )

    # --- agent_versions: additive release-management columns (§7-8, §17-25) ­
    op.add_column("agent_versions", sa.Column("release_channel_id", sa.UUID(), nullable=True))
    op.add_column("agent_versions", sa.Column("compatibility_level", sa.String(length=20), nullable=False,
                                               server_default="UNKNOWN"))
    op.add_column("agent_versions", sa.Column("signature_id", sa.String(length=255), nullable=True))
    op.add_column("agent_versions", sa.Column("snapshot_reference", sa.String(length=255), nullable=True))
    op.add_column("agent_versions", sa.Column("parent_version_id", sa.UUID(), nullable=True))
    op.add_column("agent_versions", sa.Column("rollback_target_id", sa.UUID(), nullable=True))
    op.add_column("agent_versions", sa.Column("superseded_by_id", sa.UUID(), nullable=True))
    op.add_column("agent_versions", sa.Column("release_branch", sa.String(length=100), nullable=False,
                                               server_default="main"))
    op.add_column("agent_versions", sa.Column("reviewed_by", sa.UUID(), nullable=True))
    op.add_column("agent_versions", sa.Column("revoked_reason", sa.Text(), nullable=True))
    op.add_column("agent_versions", sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True))

    op.create_foreign_key("fk_agent_versions_release_channel", "agent_versions", "agent_release_channels",
                          ["release_channel_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_agent_versions_parent_version", "agent_versions", "agent_versions",
                          ["parent_version_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_agent_versions_rollback_target", "agent_versions", "agent_versions",
                          ["rollback_target_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_agent_versions_superseded_by", "agent_versions", "agent_versions",
                          ["superseded_by_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_agent_versions_release_channel", "agent_versions", ["release_channel_id"])
    op.create_index("ix_agent_versions_parent_version", "agent_versions", ["parent_version_id"])

    # --- agent_version_snapshots (§10-14) ------------------------------------
    op.create_table(
        "agent_version_snapshots",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("agent_version_id", sa.UUID(), nullable=False, unique=True),
        sa.Column("snapshot", JSONB(), nullable=False, server_default="{}"),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_version_snapshots_version", "agent_version_snapshots", ["agent_version_id"])

    # --- agent_release_metadata (§26, §28) -----------------------------------
    op.create_table(
        "agent_release_metadata",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("agent_version_id", sa.UUID(), nullable=False, unique=True),
        sa.Column("release_name", sa.String(length=255), nullable=True),
        sa.Column("release_description", sa.Text(), nullable=True),
        sa.Column("business_justification", sa.Text(), nullable=True),
        sa.Column("change_category", sa.String(length=20), nullable=True),
        sa.Column("release_window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("support_end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_ticket", sa.String(length=100), nullable=True),
        sa.Column("source_branch", sa.String(length=200), nullable=True),
        sa.Column("commit_reference", sa.String(length=100), nullable=True),
        sa.Column("build_reference", sa.String(length=200), nullable=True),
        sa.Column("risk_score", sa.Integer(), nullable=True),
        sa.Column("documentation_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(),
                  onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_release_metadata_version", "agent_release_metadata", ["agent_version_id"])

    # --- agent_release_artifacts (§27) ---------------------------------------
    op.create_table(
        "agent_release_artifacts",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("agent_version_id", sa.UUID(), nullable=False),
        sa.Column("artifact_type", sa.String(length=30), nullable=False),
        sa.Column("reference", sa.String(length=500), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_release_artifacts_version", "agent_release_artifacts", ["agent_version_id"])

    # --- agent_release_notes (§28) -------------------------------------------
    op.create_table(
        "agent_release_notes",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("agent_version_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False, server_default="CHANGED"),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_release_notes_version", "agent_release_notes", ["agent_version_id"])

    # --- agent_version_status_history (§19, §25) -----------------------------
    op.create_table(
        "agent_version_status_history",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("agent_version_id", sa.UUID(), nullable=False),
        sa.Column("previous_status", sa.String(length=20), nullable=True),
        sa.Column("new_status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_version_status_history_version", "agent_version_status_history",
                    ["agent_version_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_version_status_history_version", table_name="agent_version_status_history")
    op.drop_table("agent_version_status_history")

    op.drop_index("ix_agent_release_notes_version", table_name="agent_release_notes")
    op.drop_table("agent_release_notes")

    op.drop_index("ix_agent_release_artifacts_version", table_name="agent_release_artifacts")
    op.drop_table("agent_release_artifacts")

    op.drop_index("ix_agent_release_metadata_version", table_name="agent_release_metadata")
    op.drop_table("agent_release_metadata")

    op.drop_index("ix_agent_version_snapshots_version", table_name="agent_version_snapshots")
    op.drop_table("agent_version_snapshots")

    op.drop_index("ix_agent_versions_parent_version", table_name="agent_versions")
    op.drop_index("ix_agent_versions_release_channel", table_name="agent_versions")
    op.drop_constraint("fk_agent_versions_superseded_by", "agent_versions", type_="foreignkey")
    op.drop_constraint("fk_agent_versions_rollback_target", "agent_versions", type_="foreignkey")
    op.drop_constraint("fk_agent_versions_parent_version", "agent_versions", type_="foreignkey")
    op.drop_constraint("fk_agent_versions_release_channel", "agent_versions", type_="foreignkey")
    op.drop_column("agent_versions", "retired_at")
    op.drop_column("agent_versions", "revoked_reason")
    op.drop_column("agent_versions", "reviewed_by")
    op.drop_column("agent_versions", "release_branch")
    op.drop_column("agent_versions", "superseded_by_id")
    op.drop_column("agent_versions", "rollback_target_id")
    op.drop_column("agent_versions", "parent_version_id")
    op.drop_column("agent_versions", "snapshot_reference")
    op.drop_column("agent_versions", "signature_id")
    op.drop_column("agent_versions", "compatibility_level")
    op.drop_column("agent_versions", "release_channel_id")

    op.drop_table("agent_release_channels")
