"""Phase M4.11 M4.11-FR-004 — the key-validation canary.

A *present* key is not necessarily the *right* key. The canary makes a wrong
key fail loud too:

- ``KEY_CANARY_PLAINTEXT`` is a fixed, **public** constant — it is not a
  secret and leaking it reveals nothing (it is in this source file).
- a canary row stores ``Fernet(key).encrypt(KEY_CANARY_PLAINTEXT)`` keyed by
  the key's non-secret fingerprint.
- ``check_key_against_canary`` decrypts the row for the active key's
  fingerprint and asserts it comes back equal to the constant. A wrong key
  cannot produce that result.

Bootstrapping the canary on an existing install: the first startup after
this migration has a valid key but no canary row. ``ensure_canary`` writes
one **only after the key is independently shown to work** — either there is
no ciphertext at all (new install), or a sample of real ciphertext decrypts
(``trial_decrypt_succeeds``). It never writes a canary for a key it cannot
otherwise trust.
"""

from __future__ import annotations

from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.models.security import KeyMaterialCanary
from app.security.encryption_provider import EncryptionKeyProvider, key_fingerprint
from app.security.install_mode import CIPHERTEXT_PROBES

MODEL_CREDENTIAL_ENCRYPTION = "MODEL_CREDENTIAL_ENCRYPTION"

#: A fixed, public marker. NOT a secret. Changing it would orphan every
#: existing canary row (they would all fail to match) — treat as frozen.
KEY_CANARY_PLAINTEXT = b"act:key-material-canary:v1:do-not-treat-as-secret"

#: how many recent ciphertext rows to sample when trial-decrypting
_TRIAL_SAMPLE = 200


class CanaryState(str):
    pass


@dataclass(frozen=True)
class CanaryResult:
    #: "MATCHED" | "TRIAL_DECRYPT" | "WROTE_NEW" | "NO_STATE"
    state: str
    fingerprint: str


def _keyring(provider: EncryptionKeyProvider) -> MultiFernet:
    return MultiFernet([Fernet(k) for k in provider.all_keys()])


def check_key_against_canary(db: Session, provider: EncryptionKeyProvider) -> bool | None:
    """``True`` — a canary row for this key's fingerprint decrypts correctly.
    ``False`` — a row exists but does not decrypt to the constant (WRONG KEY).
    ``None`` — no canary row for this fingerprint yet (undetermined here)."""
    if "key_material_canary" not in set(inspect(db.get_bind()).get_table_names()):
        return None
    fp = provider.fingerprint()
    row = db.execute(
        select(KeyMaterialCanary).where(
            KeyMaterialCanary.purpose == MODEL_CREDENTIAL_ENCRYPTION,
            KeyMaterialCanary.key_fingerprint == fp,
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    try:
        return _keyring(provider).decrypt(row.verifier.encode("ascii")) == KEY_CANARY_PLAINTEXT
    except (InvalidToken, ValueError):
        return False


def trial_decrypt_succeeds(db: Session, provider: EncryptionKeyProvider) -> bool | None:
    """Sample recent real ciphertext and try to decrypt it with the key ring.

    ``True``  — at least one sampled row decrypts (the key is the incumbent).
    ``False`` — ciphertext exists but none of the sample decrypts (WRONG KEY).
    ``None``  — there is no ciphertext to test against."""
    present = set(inspect(db.get_bind()).get_table_names())
    ring = _keyring(provider)
    any_rows = False
    for probe in CIPHERTEXT_PROBES:
        if probe.table not in present:
            continue
        where = f" WHERE {probe.predicate}" if probe.predicate else ""
        rows = db.execute(
            text(
                f"SELECT {probe.column} AS c FROM {probe.table}{where} "
                f"ORDER BY created_at DESC LIMIT :n"
            ),
            {"n": _TRIAL_SAMPLE},
        ).all()
        for (ciphertext,) in rows:
            any_rows = True
            try:
                ring.decrypt(ciphertext.encode("ascii"))
                return True
            except (InvalidToken, ValueError, AttributeError):
                continue
    return None if not any_rows else False


def write_canary(db: Session, provider: EncryptionKeyProvider) -> None:
    """Upsert the canary row for the active key's fingerprint. Idempotent."""
    fp = provider.fingerprint()
    existing = db.execute(
        select(KeyMaterialCanary).where(
            KeyMaterialCanary.purpose == MODEL_CREDENTIAL_ENCRYPTION,
            KeyMaterialCanary.key_fingerprint == fp,
        )
    ).scalar_one_or_none()
    token = Fernet(provider.get_key()).encrypt(KEY_CANARY_PLAINTEXT).decode("ascii")
    if existing is None:
        db.add(
            KeyMaterialCanary(
                purpose=MODEL_CREDENTIAL_ENCRYPTION,
                key_fingerprint=fp,
                verifier=token,
                key_provider=provider.name,
            )
        )
    else:
        existing.verifier = token
        existing.key_provider = provider.name
    db.commit()
