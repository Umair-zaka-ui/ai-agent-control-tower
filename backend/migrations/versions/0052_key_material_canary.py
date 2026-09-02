"""Phase M4.11 - key-material recovery & fail-loud integrity.

One new table, no change to any existing one, no data backfill. Purely
additive, reversible, downgrade-tested. It changes **no decrypt behaviour**
for any existing row: an installation that never writes a canary row falls
back to trial-decrypting real ciphertext (``app/security/canary.py``), and
existing ciphertext is read exactly as before through the same
``credential_crypto`` key ring.

## ``key_material_canary``

A **verifier**: ``Fernet(key).encrypt(<public constant>)`` keyed by the
key's non-secret fingerprint. On startup the platform decrypts the row for
the active key's fingerprint; if it does not come back equal to the
constant, the key is wrong, and the platform fails loud rather than
encrypting new data under a key that cannot read the old data
(M4.11-FR-004). The row holds no key and no secret -- only a ciphertext of
a public constant and a domain-separated hash prefix.

``uq_key_material_canary_purpose_fp`` keeps one row per (purpose,
fingerprint) so a rotation registers a new verifier alongside the old one
rather than overwriting it.

Revision ID: 0052_key_material_canary
Revises: 0051_telemetry_privacy
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0052_key_material_canary"
down_revision = "0051_telemetry_privacy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "key_material_canary",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("key_fingerprint", sa.String(length=32), nullable=False),
        sa.Column("verifier", sa.Text(), nullable=False),
        sa.Column("key_provider", sa.String(length=32), nullable=False, server_default="LOCAL"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("purpose", "key_fingerprint", name="uq_key_material_canary_purpose_fp"),
    )


def downgrade() -> None:
    op.drop_table("key_material_canary")
