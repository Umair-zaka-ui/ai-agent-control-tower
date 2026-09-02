"""Phase M4.11a M4.11a-FR-001..004 — the durable bootstrap-completed marker.

**The correction M4.11a makes:** presence of encrypted state is a
*sufficient* EXISTING signal (ciphertext ⇒ definitely established) but **not
a necessary one** (no ciphertext proves nothing — a brand-new empty DB, an
established DB that never stored a credential, a restored DB whose
ciphertext tables happen to be empty, and a half-initialised DB all present
the same "no ciphertext").

``installation_bootstrap`` collapses that ambiguity. It is a positive fact,
written **once** — at deliberate bootstrap, or backfilled once at startup
after an existing key is verified. Thereafter its presence means EXISTING
unambiguously, and its absence means exactly one thing: this installation
has never completed key bootstrap.

The row holds only non-secret provenance — a timestamp, the active key's
non-secret fingerprint, the provider name, a schema tag. Never a key or a
secret.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.models.security import InstallationBootstrap

KEYRING_SCHEMA_VERSION = "m4.11a/1"


def _table_present(db: Session) -> bool:
    return "installation_bootstrap" in set(inspect(db.get_bind()).get_table_names())


def marker_present(db: Session) -> bool:
    """True iff this installation has a recorded bootstrap-completed fact."""
    if not _table_present(db):
        return False
    return db.execute(select(InstallationBootstrap.id).limit(1)).first() is not None


def read_marker(db: Session) -> InstallationBootstrap | None:
    if not _table_present(db):
        return None
    return db.execute(select(InstallationBootstrap).limit(1)).scalar_one_or_none()


def record_bootstrap(db: Session, provider, *, recorded_via: str) -> InstallationBootstrap:
    """Write the singleton marker if absent. Idempotent — a second call (or a
    restart mid-upgrade) returns the existing row and never duplicates.

    ``recorded_via`` is ``"bootstrap"`` (a deliberate provision) or
    ``"backfill"`` (recorded at startup after an existing key was verified —
    M4.11a-FR-009)."""
    existing = read_marker(db)
    if existing is not None:
        return existing
    row = InstallationBootstrap(
        singleton=True,
        bootstrapped_at=datetime.now(timezone.utc),
        active_key_fingerprint=provider.fingerprint(),
        key_provider=provider.name,
        keyring_schema_version=KEYRING_SCHEMA_VERSION,
        recorded_via=recorded_via,
    )
    db.add(row)
    db.commit()
    return row
