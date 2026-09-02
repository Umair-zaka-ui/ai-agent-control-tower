"""Phase M4.11 / M4.11a — NEW_INSTALL vs EXISTING_INSTALL.

**Phase M4.11a corrected the signal.** M4.11 inferred NEW from the *absence
of encrypted state*, which is unsafe: an established installation can
legitimately hold organizations, agents, policies and deployments while
having *zero* encrypted credential rows — and under that logic, if it lost
its key, it was classified NEW and bootstrap could silently mint a fresh
cryptographic identity.

The corrected rule (M4.11a-FR-003):

- **EXISTING** iff the durable ``installation_bootstrap`` marker is present
  **OR** any encrypted/signed state exists. Ciphertext / a signed
  attestation remains a *sufficient* fast-path — it just is no longer the
  *only* signal.
- **NEW** iff the marker is absent **AND** there is no encrypted or signed
  state. Even then, bootstrap stays deliberate (the
  ``ENCRYPTION_KEY_ALLOW_BOOTSTRAP`` gate + the ``keys bootstrap`` CLI) —
  never automatic.

So a missing key file *never by itself* implies NEW. NEW is a positive
durable fact (the marker being absent), and every ambiguous shape
(established-but-no-ciphertext, restored, cloned, half-initialised) falls on
the safe EXISTING / fail-loud side.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.security.installation import marker_present


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
    #: M4.11a — the durable bootstrap-completed marker is present
    bootstrap_marker: bool = False

    @property
    def has_encrypted_state(self) -> bool:
        return bool(self.encrypted_state_tables)

    @property
    def has_signed_state(self) -> bool:
        return bool(self.signed_state_tables)

    @property
    def has_any_state(self) -> bool:
        return self.has_encrypted_state or self.has_signed_state

    @property
    def reason(self) -> str:
        if self.bootstrap_marker:
            return "bootstrap marker present"
        if self.has_encrypted_state:
            return "encrypted state: " + ", ".join(self.encrypted_state_tables)
        if self.has_signed_state:
            return "signed state: " + ", ".join(self.signed_state_tables)
        return "no marker and no encrypted or signed state"


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
    marker = marker_present(db)
    encrypted = _tables_with_rows(db, CIPHERTEXT_PROBES)
    signed = _tables_with_rows(db, SIGNED_STATE_PROBES)
    mode = InstallMode.EXISTING if (marker or encrypted or signed) else InstallMode.NEW
    return InstallModeReport(
        mode=mode,
        encrypted_state_tables=encrypted,
        signed_state_tables=signed,
        bootstrap_marker=marker,
    )
