"""Phase M4.11 M4.11-FR-001..004, M4.11-FR-030..032 — the fail-loud check.

``verify_key_material(db)`` is called once at startup (``app.main``'s
lifespan), before the platform serves any request that could decrypt or
sign. It is a pure read plus, at most, one idempotent canary write. It
either returns a ``KeyIntegrityReport`` (safe to log — no secrets) or raises
``KeyMaterialError`` (also safe to log), and **it never generates a
replacement key for an established installation**.

The decision table (encryption):

| install mode | key present | canary        | outcome                        |
|--------------|-------------|---------------|--------------------------------|
| EXISTING     | no          | —             | FAIL LOUD (lost key)           |
| EXISTING     | yes         | matches       | OK (steady state)              |
| EXISTING     | yes         | mismatches    | FAIL LOUD (wrong key)          |
| EXISTING     | yes         | absent        | trial-decrypt real ciphertext: |
|              |             |               |  decrypts → OK, write canary   |
|              |             |               |  fails   → FAIL LOUD (wrong)   |
| NEW          | no          | —             | bootstrap iff allowed, else    |
|              |             |               |  FAIL LOUD (needs bootstrap)   |
| NEW          | yes         | —             | OK, write canary               |

Signing is checked independently: every ``signing_keys`` row must still have
a usable private key on the provider whose public half matches the database.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.security.canary import check_key_against_canary, trial_decrypt_succeeds, write_canary
from app.security.encryption_provider import EncryptionKeyProvider, get_encryption_key_provider
from app.security.errors import KeyMaterialError
from app.security.install_mode import InstallMode, detect_install_mode

logger = logging.getLogger(__name__)


@dataclass
class KeyIntegrityReport:
    install_mode: str
    encryption: dict = field(default_factory=dict)
    signing: dict = field(default_factory=dict)

    def as_log_line(self) -> str:
        enc = self.encryption
        sig = self.signing
        return (
            f"key-material integrity OK — install={self.install_mode} "
            f"encryption[provider={enc.get('provider')} fp={enc.get('fingerprint')} "
            f"validation={enc.get('validation')}] "
            f"signing[keys={sig.get('keys_checked', 0)} validation={sig.get('validation')}]"
        )


# --------------------------------------------------------------------------- #
# Encryption
# --------------------------------------------------------------------------- #
def verify_encryption_material(db: Session, *, allow_bootstrap: bool = False) -> dict:
    report = detect_install_mode(db)
    provider = get_encryption_key_provider()
    established = report.has_encrypted_state

    if not provider.is_present():
        if established:
            raise KeyMaterialError(
                "ENCRYPTION_KEY_MISSING_ESTABLISHED_INSTALL",
                (
                    "the database holds encrypted data ("
                    + ", ".join(report.encrypted_state_tables)
                    + ") but no provider-credential encryption key is available"
                ),
                remediation=(
                    "restore backend/.keys/model_credentials.key (or set "
                    "MODEL_CREDENTIAL_ENCRYPTION_KEY) from the recovery archive — see "
                    "docs/security/key-management.md; do NOT start the platform with a fresh key, "
                    "it would leave every stored secret undecryptable"
                ),
            )
        if allow_bootstrap or settings.ENCRYPTION_KEY_ALLOW_BOOTSTRAP:
            provider.bootstrap()
            write_canary(db, provider)
            return {
                "provider": provider.name,
                "fingerprint": provider.fingerprint(),
                "validation": "BOOTSTRAPPED",
            }
        raise KeyMaterialError(
            "ENCRYPTION_KEY_MISSING_NEW_INSTALL",
            "no provider-credential encryption key is configured and this looks like a new installation",
            remediation=(
                "run `python -m app.security.keys bootstrap` to provision one deliberately, or set "
                "MODEL_CREDENTIAL_ENCRYPTION_KEY explicitly"
            ),
        )

    # Present — but is it the right one?
    fingerprint = provider.fingerprint()  # also validates base64/length (raises KeyMaterialError)

    canary = check_key_against_canary(db, provider)
    if canary is True:
        return {"provider": provider.name, "fingerprint": fingerprint, "validation": "CANARY_MATCH"}
    if canary is False:
        raise KeyMaterialError(
            "ENCRYPTION_KEY_MISMATCH",
            "the configured encryption key does not match the key that wrote this database's canary",
            remediation=(
                "restore the correct key from the recovery archive; a key that fails the canary must "
                "never be used to write new data"
            ),
        )

    # No canary row for this fingerprint yet — prove the key another way.
    trial = trial_decrypt_succeeds(db, provider)
    if trial is False:
        raise KeyMaterialError(
            "ENCRYPTION_KEY_CANNOT_DECRYPT",
            "the configured encryption key cannot decrypt this database's existing ciphertext",
            remediation=(
                "restore the correct key from the recovery archive — see docs/security/key-management.md"
            ),
        )
    write_canary(db, provider)
    return {
        "provider": provider.name,
        "fingerprint": fingerprint,
        "validation": "TRIAL_DECRYPT" if trial else "REGISTERED",
    }


# --------------------------------------------------------------------------- #
# Signing
# --------------------------------------------------------------------------- #
def verify_signing_material_for_key(provider, key) -> None:
    """Raise ``KeyMaterialError`` if ``provider`` has lost or mismatched the
    private key for signing-key row ``key``. A no-op for a provider type
    that validates elsewhere (e.g. a future Key Vault provider)."""
    from app.runtime.versioning.signing.local import LocalKeyProvider

    if not isinstance(provider, LocalKeyProvider):
        return
    key_id, version = key.key_id, key.current_version
    if not provider.has_private_key(key_id, version):
        raise KeyMaterialError(
            "SIGNING_PRIVATE_KEY_MISSING",
            (
                f"signing identity '{key_id}' v{version} is recorded in the database but its private "
                "key is not present"
            ),
            remediation=(
                f"restore backend/.keys/{key_id}.v{version}.pem from the recovery archive; historical "
                "signatures still verify from the public keys in the database, but this identity "
                "cannot sign again without its private key"
            ),
        )
    try:
        derived = provider.derive_public_key_pem(key_id, version).decode("utf-8").strip()
    except (ValueError, TypeError) as exc:
        raise KeyMaterialError(
            "SIGNING_PRIVATE_KEY_UNREADABLE",
            f"signing identity '{key_id}' v{version} private key file is present but not a readable key",
            remediation=f"restore a valid backend/.keys/{key_id}.v{version}.pem from the recovery archive",
        ) from exc
    if derived.replace("\r\n", "\n") != (key.public_key_pem or "").strip().replace("\r\n", "\n"):
        raise KeyMaterialError(
            "SIGNING_KEY_MISMATCH",
            (
                f"the on-disk private key for signing identity '{key_id}' v{version} does not match the "
                "public key recorded in the database"
            ),
            remediation=(
                f"restore the correct backend/.keys/{key_id}.v{version}.pem from the recovery archive — a "
                "mismatched key cannot produce verifiable signatures for this identity"
            ),
        )


def verify_signing_material(db: Session) -> dict:
    """Validate the signing *identity that will sign next* — the configured
    default key — plus a guard for a wholesale loss of the signing catalog.

    Historical per-version keys are deliberately out of scope: their private
    keys being gone means "cannot re-sign that old version" (which never
    happens), not "the platform must not start". Old signatures stay
    verifiable from the public keys in ``signing_key_versions`` regardless.
    """
    from sqlalchemy import func

    from app.models.runtime import AgentVersionSignature, SigningKey
    from app.runtime.versioning.signing.registry import get_signing_provider

    provider = get_signing_provider()
    default_id = settings.SIGNING_DEFAULT_KEY_ID

    any_signing_key = db.execute(select(func.count()).select_from(SigningKey)).scalar_one()
    any_signature = db.execute(select(AgentVersionSignature.id).limit(1)).first() is not None
    if any_signature and any_signing_key == 0:
        raise KeyMaterialError(
            "SIGNING_KEYS_LOST",
            "signed attestations exist in the database but the signing_keys catalog is empty",
            remediation="restore the database including signing_keys, or restore from a consistent snapshot",
        )

    key = db.execute(select(SigningKey).where(SigningKey.key_id == default_id)).scalar_one_or_none()
    if key is None:
        return {"keys_checked": 0, "validation": "NO_DEFAULT_IDENTITY", "signed_state": any_signature}

    verify_signing_material_for_key(provider, key)
    return {"keys_checked": 1, "validation": "OK", "signed_state": any_signature}


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def verify_key_material(db: Session, *, allow_bootstrap: bool = False) -> KeyIntegrityReport:
    """The one call ``app.main``'s lifespan makes. Raises ``KeyMaterialError``
    (loud, deterministic, no secret) or returns a loggable report."""
    if not settings.KEY_MATERIAL_FAIL_LOUD:
        logger.warning(
            "KEY_MATERIAL_FAIL_LOUD is disabled — skipping the key-material integrity check. "
            "This is unsafe outside a throwaway environment."
        )
        return KeyIntegrityReport(install_mode="UNCHECKED")

    mode = detect_install_mode(db).mode
    encryption = verify_encryption_material(db, allow_bootstrap=allow_bootstrap)
    signing = verify_signing_material(db)
    report = KeyIntegrityReport(
        install_mode=mode.value if isinstance(mode, InstallMode) else str(mode),
        encryption=encryption,
        signing=signing,
    )
    logger.info(report.as_log_line())
    return report
