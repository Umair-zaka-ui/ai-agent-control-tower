"""Phase M4.11a - the durable bootstrap marker.

One new table, ``installation_bootstrap``, no change to any existing one, no
data backfill in this migration. Purely additive, reversible,
downgrade-tested, tenant-neutral. It changes **no decrypt behaviour** for
any existing row.

## Why

M4.11's ``detect_install_mode`` inferred "NEW installation" from the
*absence of encrypted state*. That is unsafe: an established installation
can legitimately have organizations, agents, policies and deployments while
holding zero encrypted credential rows — and under that logic, if it lost
its key, it was classified NEW and bootstrap could silently mint a fresh
cryptographic identity. This table replaces inference-from-absence with a
**positive, once-written fact**: "this installation completed key
bootstrap". Its presence ⇒ EXISTING, unambiguously. NEW now means the
marker is absent *and* there is no encrypted/signed state.

## ``installation_bootstrap``

Platform-scoped, singular — the installation's identity, not tenant data.
``singleton`` is pinned true by a CHECK and made unique, so exactly one row
is possible. Holds only non-secret provenance (timestamp, the active key's
non-secret fingerprint, the provider name, a keyring schema tag,
``recorded_via``). No key, no secret.

The marker is written by a deliberate bootstrap
(``python -m app.security.keys bootstrap`` /
``verify_key_material(allow_bootstrap=True)``) or **backfilled once at
startup** after ``verify_key_material`` confirms an existing key decrypts
real state / matches the canary — so an install that bootstrapped under
M4.11 becomes correctly EXISTING with no window in which it reads as NEW.

Revision ID: 0053_installation_bootstrap
Revises: 0052_key_material_canary
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0053_installation_bootstrap"
down_revision = "0052_key_material_canary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "installation_bootstrap",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("singleton", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("bootstrapped_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active_key_fingerprint", sa.String(length=32), nullable=False),
        sa.Column("key_provider", sa.String(length=32), nullable=False, server_default="LOCAL"),
        sa.Column("keyring_schema_version", sa.String(length=32), nullable=False, server_default="m4.11a/1"),
        sa.Column("recorded_via", sa.String(length=16), nullable=False, server_default="bootstrap"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("singleton IS TRUE", name="ck_installation_bootstrap_singleton_true"),
        sa.UniqueConstraint("singleton", name="uq_installation_bootstrap_singleton"),
    )


def downgrade() -> None:
    op.drop_table("installation_bootstrap")
