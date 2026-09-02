"""Phase M4.11 / M4.11a — the fail-loud key-material check.

``verify_key_material(db)`` is called once at startup (``app.main``'s
lifespan), before the platform serves any request that could decrypt or
sign. It is a pure read plus, at most, one idempotent canary write and one
idempotent bootstrap-marker write. It either returns a ``KeyIntegrityReport``
(safe to log — no secrets) or raises ``KeyMaterialError`` (also safe to
log), and **it never generates a replacement key for an established
installation**.

**Phase M4.11a — the five-state key taxonomy** (M4.11a-FR-020). Startup key
evaluation deterministically resolves to exactly one:

| state                            | when                                                       | outcome |
|----------------------------------|------------------------------------------------------------|---------|
| ``KEY_PROVIDER_UNAVAILABLE``     | the provider backend can't be reached (a KMS/Vault outage) | FAIL LOUD — never an install-mode signal, never bootstraps |
| ``KEY_ABSENT``                   | established install, no key found                          | FAIL LOUD (lost key) |
| ``KEY_MALFORMED``                | a key is present but not a structurally valid key          | FAIL LOUD |
| ``KEY_PRESENT_BUT_WRONG``        | valid structure, fails the canary / can't decrypt real data| FAIL LOUD (wrong key) |
| ``INSTALLATION_NEVER_BOOTSTRAPPED`` | no marker, no encrypted/signed state, **no key**         | the only path to a deliberate bootstrap |
| (``OK``)                         | key present + canary matches / trial-decrypt succeeds       | serve; backfill the marker if absent |

An install-mode of EXISTING now comes from **the durable
``installation_bootstrap`` marker OR any encrypted/signed state** — a
missing key file, or an empty set of ciphertext tables, no longer implies
NEW.

Signing is checked independently: the configured default signing identity
must still have a usable private key on the provider whose public half
matches the database.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.security.canary import check_key_against_canary, trial_decrypt_succeeds, write_canary
from app.security.encryption_provider import (
    EncryptionKeyProvider,
    ProviderUnavailableError,
    get_encryption_key_provider,
)
from app.security.errors import KeyMaterialError
from app.security.install_mode import InstallMode, detect_install_mode
from app.security.installation import marker_present, record_bootstrap

logger = logging.getLogger(__name__)


class KeyState(str, enum.Enum):
    OK = "OK"
    KEY_ABSENT = "KEY_ABSENT"
    KEY_MALFORMED = "KEY_MALFORMED"
    KEY_PRESENT_BUT_WRONG = "KEY_PRESENT_BUT_WRONG"
    KEY_PROVIDER_UNAVAILABLE = "KEY_PROVIDER_UNAVAILABLE"
    INSTALLATION_NEVER_BOOTSTRAPPED = "INSTALLATION_NEVER_BOOTSTRAPPED"


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
            f"state={enc.get('key_state')} validation={enc.get('validation')}] "
            f"signing[keys={sig.get('keys_checked', 0)} validation={sig.get('validation')}]"
        )


def _ok(provider: EncryptionKeyProvider, validation: str) -> dict:
    return {
        "provider": provider.name,
        "fingerprint": provider.fingerprint(),
        "key_state": KeyState.OK.value,
        "validation": validation,
    }


# --------------------------------------------------------------------------- #
# Encryption
# --------------------------------------------------------------------------- #
def verify_encryption_material(db: Session, *, allow_bootstrap: bool = False) -> dict:
    report = detect_install_mode(db)
    established = report.mode is InstallMode.EXISTING
    provider = get_encryption_key_provider()

    # ---- KEY_PROVIDER_UNAVAILABLE — evaluated first, and NOT an install-mode
    #      signal: a transient provider outage never makes an established
    #      install look NEW and never falls back to generating a key.
    try:
        provider.check_available()
    except ProviderUnavailableError as exc:
        raise KeyMaterialError(
            "ENCRYPTION_KEY_PROVIDER_UNAVAILABLE",
            f"the encryption key provider '{provider.name}' could not be reached",
            remediation=(
                "restore connectivity to the key provider and restart; the platform will not start "
                "without its key provider and will never fall back to generating a key"
            ),
        ) from exc

    # ---- KEY_ABSENT / INSTALLATION_NEVER_BOOTSTRAPPED
    if not provider.is_present():
        if established:
            raise KeyMaterialError(
                "ENCRYPTION_KEY_MISSING_ESTABLISHED_INSTALL",
                (
                    f"this is an established installation ({report.reason}) but no "
                    "provider-credential encryption key is available"
                ),
                remediation=(
                    "restore backend/.keys/model_credentials.key (or set "
                    "MODEL_CREDENTIAL_ENCRYPTION_KEY) from the recovery archive — see "
                    "docs/security/key-management.md; do NOT start the platform with a fresh key, "
                    "it would leave every stored secret undecryptable"
                ),
            )
        # marker absent AND no encrypted/signed state AND no key -> the one bootstrap-eligible state
        if allow_bootstrap or settings.ENCRYPTION_KEY_ALLOW_BOOTSTRAP:
            provider.bootstrap()
            provider = get_encryption_key_provider()
            write_canary(db, provider)
            record_bootstrap(db, provider, recorded_via="bootstrap")
            return _ok(provider, "BOOTSTRAPPED")
        raise KeyMaterialError(
            "INSTALLATION_NEVER_BOOTSTRAPPED",
            "this installation has no encryption key and no record of ever completing key bootstrap",
            remediation=(
                "for a genuinely new installation run `python -m app.security.keys bootstrap` "
                "(or set MODEL_CREDENTIAL_ENCRYPTION_KEY and ENCRYPTION_KEY_ALLOW_BOOTSTRAP); "
                "for a restore, restore the key material from the recovery archive"
            ),
        )

    # ---- KEY_MALFORMED — a key is present but not a valid key structure
    try:
        provider.get_key()
    except KeyMaterialError as exc:
        if exc.code == "ENCRYPTION_KEY_INVALID":
            raise KeyMaterialError(
                "ENCRYPTION_KEY_MALFORMED",
                "an encryption key is present but is not a structurally valid key",
                remediation=(
                    "restore a valid key from the recovery archive; a malformed key is never used "
                    "and is never replaced automatically"
                ),
            ) from exc
        raise

    # ---- KEY_PRESENT_BUT_WRONG vs OK
    canary = check_key_against_canary(db, provider)
    if canary is True:
        _backfill_marker(db, provider, report)
        return _ok(provider, "CANARY_MATCH")
    if canary is False:
        raise KeyMaterialError(
            "ENCRYPTION_KEY_MISMATCH",
            "the configured encryption key does not match the key that wrote this database's canary",
            remediation=(
                "restore the correct key from the recovery archive; a key that fails the canary must "
                "never be used to write new data"
            ),
        )

    # No canary row for this fingerprint yet — prove the key against real data.
    trial = trial_decrypt_succeeds(db, provider)
    if trial is False:
        raise KeyMaterialError(
            "ENCRYPTION_KEY_CANNOT_DECRYPT",
            "the configured encryption key cannot decrypt this database's existing ciphertext",
            remediation=(
                "restore the correct key from the recovery archive — see docs/security/key-management.md"
            ),
        )
    if trial is True:
        write_canary(db, provider)
        _backfill_marker(db, provider, report)
        return _ok(provider, "TRIAL_DECRYPT")

    # trial is None — no canary and no ciphertext to verify the key against.
    if established:
        # marker present or signed state exists, but nothing decryptable to check.
        raise KeyMaterialError(
            "ENCRYPTION_KEY_UNVERIFIED_ESTABLISHED_INSTALL",
            (
                f"this is an established installation ({report.reason}) but the encryption key "
                "cannot be verified — there is no canary and no encrypted data to test it against"
            ),
            remediation=(
                "restore the key material and the key_material_canary rows from a consistent "
                "recovery archive; do not start with an unverified key on an established install"
            ),
        )
    # not established (no marker, no state) but a key IS present: half-init.
    if allow_bootstrap or settings.ENCRYPTION_KEY_ALLOW_BOOTSTRAP:
        # deliberate: adopt this operator-provided key as the installation identity
        write_canary(db, provider)
        record_bootstrap(db, provider, recorded_via="bootstrap")
        return _ok(provider, "ADOPTED_KEY")
    raise KeyMaterialError(
        "INSTALLATION_BOOTSTRAP_INCOMPLETE",
        (
            "an encryption key is present but this installation has no record of completing key "
            "bootstrap and no data to verify the key against"
        ),
        remediation=(
            "if this is a fresh install, run `python -m app.security.keys bootstrap` "
            "(it adopts a present key); if this is a restore, also restore the database "
            "(which carries the bootstrap marker) and the canary rows"
        ),
    )


def _backfill_marker(db: Session, provider: EncryptionKeyProvider, report) -> None:
    """M4.11a-FR-009 — once an existing key is *verified*, record the durable
    marker if it is not already there. Idempotent; safe mid-upgrade."""
    if not report.bootstrap_marker and marker_present(db) is False:
        record_bootstrap(db, provider, recorded_via="backfill")


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

    # Encryption first — it may backfill the bootstrap marker, so read the
    # authoritative install mode after it runs.
    encryption = verify_encryption_material(db, allow_bootstrap=allow_bootstrap)
    signing = verify_signing_material(db)
    mode = detect_install_mode(db).mode
    report = KeyIntegrityReport(
        install_mode=mode.value if isinstance(mode, InstallMode) else str(mode),
        encryption=encryption,
        signing=signing,
    )
    logger.info(report.as_log_line())
    return report
