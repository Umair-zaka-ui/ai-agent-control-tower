"""Phase 5.2.4 - Cryptographic Signing, Provenance & Portable Attestation.

Two purposes, additive, same philosophy as every migration since 0025:

1. **Canonical serialization migration.** ``agent_versions`` and
   ``agent_version_snapshots`` gain a ``checksum_algorithm`` column,
   defaulting to ``'legacy-sha256'`` for every row that exists before this
   migration runs (Phase 5.0/5.2 Part 1's ``json.dumps``-based checksum).
   New rows created after this phase ships set it to ``'canonical-sha256'``
   explicitly at the application layer (see
   ``app/runtime/services.py::AgentVersionService.create`` and
   ``app/runtime/versioning/snapshot.py::SnapshotBuilderService``) — this
   migration does **not** recompute or rewrite a single existing checksum
   value; verification branches on the column instead (see
   ``app/runtime/services.py::_verify_checksum``). Both checksum columns
   are also widened from 64 to 80 characters to fit the new
   algorithm-prefixed format (``"sha256:<64 hex>"`` is 71 characters;
   legacy bare 64-char hex values are unaffected).

2. **Signing & provenance schema.** Four new tables:

   - ``signing_keys`` / ``signing_key_versions`` — the DB record of a
     signing key's *public* material and lifecycle (active/rotated/
     revoked); never private key material, which lives only on disk (or,
     later, in Azure Key Vault) behind the ``SigningProvider`` abstraction
     in ``app/runtime/versioning/signing/``.
   - ``agent_version_signatures`` — one row per signature over a version's
     manifest digest (the automatic ``PUBLISHER`` signature at publish
     time, plus any number of later ``COUNTERSIGN`` rows).
   - ``agent_version_provenance`` — one row per version recording who/
     what/where produced it, the source for the attestation document's
     ``predicate.provenance`` section.

   ``agent_versions`` also gains ``signed_at``/``manifest_digest``.
   ``agent_versions.signature_id`` (added by 0025, always null until now)
   is wired to the primary (``PUBLISHER``) signature's id at publish time
   rather than dropped — see docs/runtime/versioning.md's Phase 5.2.4
   section for the rationale.

Revision ID: 0027_version_signing
Revises: 0026_version_compatibility
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0027_version_signing"
down_revision: str | None = "0026_version_compatibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Canonical serialization migration -----------------------------------
    op.alter_column("agent_versions", "checksum", type_=sa.String(length=80))
    op.alter_column("agent_version_snapshots", "checksum", type_=sa.String(length=80))

    op.add_column("agent_versions", sa.Column("checksum_algorithm", sa.String(length=20), nullable=False,
                                               server_default="legacy-sha256"))
    op.add_column("agent_version_snapshots", sa.Column("checksum_algorithm", sa.String(length=20), nullable=False,
                                                        server_default="legacy-sha256"))

    op.add_column("agent_versions", sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agent_versions", sa.Column("manifest_digest", sa.String(length=80), nullable=True))

    # --- signing_keys ---------------------------------------------------------
    op.create_table(
        "signing_keys",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("key_id", sa.String(length=128), nullable=False, unique=True),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="LOCAL"),
        sa.Column("algorithm", sa.String(length=32), nullable=False, server_default="ED25519"),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("public_key_pem", sa.Text(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(),
                  onupdate=sa.func.now()),
    )

    # --- signing_key_versions --------------------------------------------------
    op.create_table(
        "signing_key_versions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("signing_key_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("public_key_pem", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["signing_key_id"], ["signing_keys.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("signing_key_id", "version", name="uq_signing_key_versions_key_version"),
    )
    op.create_index("ix_signing_key_versions_key", "signing_key_versions", ["signing_key_id"])

    # --- agent_version_signatures -----------------------------------------------
    op.create_table(
        "agent_version_signatures",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("agent_version_id", sa.UUID(), nullable=False),
        sa.Column("manifest_digest", sa.String(length=80), nullable=False),
        sa.Column("signature", sa.LargeBinary(), nullable=False),
        sa.Column("algorithm", sa.String(length=32), nullable=False),
        sa.Column("signing_key_id", sa.UUID(), nullable=False),
        sa.Column("signing_key_version", sa.Integer(), nullable=False),
        sa.Column("signature_type", sa.String(length=32), nullable=False, server_default="PUBLISHER"),
        sa.Column("dsse_envelope", JSONB(), nullable=False, server_default="{}"),
        sa.Column("verification_status", sa.String(length=20), nullable=False, server_default="UNVERIFIED"),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("signed_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["signing_key_id"], ["signing_keys.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["signed_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_agent_version_signatures_version", "agent_version_signatures", ["agent_version_id"])

    # --- agent_version_provenance ------------------------------------------------
    op.create_table(
        "agent_version_provenance",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("agent_version_id", sa.UUID(), nullable=False, unique=True),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False, server_default="USER"),
        sa.Column("source_repository", sa.Text(), nullable=True),
        sa.Column("source_commit", sa.String(length=64), nullable=True),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        sa.Column("build_environment", sa.String(length=128), nullable=True),
        sa.Column("builder_identity", sa.Text(), nullable=False),
        sa.Column("source_ip", sa.String(length=45), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        sa.Column("attestation_document", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_version_provenance_version", "agent_version_provenance", ["agent_version_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_version_provenance_version", table_name="agent_version_provenance")
    op.drop_table("agent_version_provenance")

    op.drop_index("ix_agent_version_signatures_version", table_name="agent_version_signatures")
    op.drop_table("agent_version_signatures")

    op.drop_index("ix_signing_key_versions_key", table_name="signing_key_versions")
    op.drop_table("signing_key_versions")

    op.drop_table("signing_keys")

    op.drop_column("agent_versions", "manifest_digest")
    op.drop_column("agent_versions", "signed_at")
    op.drop_column("agent_version_snapshots", "checksum_algorithm")
    op.drop_column("agent_versions", "checksum_algorithm")

    op.alter_column("agent_version_snapshots", "checksum", type_=sa.String(length=64))
    op.alter_column("agent_versions", "checksum", type_=sa.String(length=64))
