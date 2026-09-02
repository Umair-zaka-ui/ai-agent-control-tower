"""Phase M4.11 M4.11-FR-010..013 — NEW_INSTALL vs EXISTING_INSTALL_WITH_LOST_KEY.

**The signal is the presence of encrypted state in the database — not the
absence of a key file.** "File missing ⇒ new install ⇒ generate" is exactly
the hazard M4.11 closes. The correct, un-foolable rule is the inverse:

- if the database holds *any* ciphertext (a provider / connector / tool
  credential, a cached OAuth token, a federation client secret) or *any*
  signed attestation, this is an **EXISTING** install. A missing or wrong
  key is lost/invalid key material → fail loud, never bootstrap.
- only a database with *no* encrypted state at all is a **NEW** install,
  where a deliberate bootstrap is safe.

A restored database with rows but no key is therefore always EXISTING — the
rows are the proof — which is the negative-proof anchor (M4.11-FR-012).

The probe is a cheap ``SELECT 1 ... LIMIT 1`` per table, guarded by a live
table-existence check so it is safe to run at any point after migrations.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session


class InstallMode(str, enum.Enum):
    NEW = "NEW_INSTALL"
    EXISTING = "EXISTING_INSTALL"


@dataclass(frozen=True)
class EncryptedStateProbe:
    table: str
    column: str
    #: extra predicate, e.g. the column being nullable
    predicate: str = ""

    @property
    def sql(self) -> str:
        where = f" WHERE {self.predicate}" if self.predicate else ""
        return f"SELECT 1 FROM {self.table}{where} LIMIT 1"


# Every table that stores a Fernet ciphertext produced with the platform
# encryption key. Keep this list in lockstep with the encrypt/decrypt call
# sites (asserted structurally by test_key_material_integrity).
CIPHERTEXT_PROBES: tuple[EncryptedStateProbe, ...] = (
    EncryptedStateProbe("provider_credentials", "encrypted_secret"),
    EncryptedStateProbe("tool_credentials", "encrypted_secret"),
    EncryptedStateProbe("connector_credentials", "encrypted_secret"),
    EncryptedStateProbe("connector_oauth_tokens", "encrypted_access_token"),
    EncryptedStateProbe(
        "identity_federation_configs", "encrypted_client_secret",
        predicate="encrypted_client_secret IS NOT NULL",
    ),
)

# Signed state — an established *signing* identity, independent of the
# encryption key.
SIGNED_STATE_PROBES: tuple[EncryptedStateProbe, ...] = (
    EncryptedStateProbe("agent_version_signatures", "signature"),
    EncryptedStateProbe("signing_keys", "public_key_pem"),
)


@dataclass(frozen=True)
class InstallModeReport:
    mode: InstallMode
    encrypted_state_tables: tuple[str, ...]
    signed_state_tables: tuple[str, ...]

    @property
    def has_encrypted_state(self) -> bool:
        return bool(self.encrypted_state_tables)

    @property
    def has_signed_state(self) -> bool:
        return bool(self.signed_state_tables)


def _tables_with_rows(db: Session, probes: tuple[EncryptedStateProbe, ...]) -> tuple[str, ...]:
    present = set(inspect(db.get_bind()).get_table_names())
    hits: list[str] = []
    for probe in probes:
        if probe.table not in present:
            continue
        if db.execute(text(probe.sql)).first() is not None:
            hits.append(probe.table)
    return tuple(hits)


def detect_install_mode(db: Session) -> InstallModeReport:
    encrypted = _tables_with_rows(db, CIPHERTEXT_PROBES)
    signed = _tables_with_rows(db, SIGNED_STATE_PROBES)
    mode = InstallMode.EXISTING if (encrypted or signed) else InstallMode.NEW
    return InstallModeReport(mode=mode, encrypted_state_tables=encrypted, signed_state_tables=signed)
