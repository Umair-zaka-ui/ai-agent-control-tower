"""Phase M4.11 M4.11-FR-010..013 — the deliberate new-install bootstrap.

Bootstrap is **explicit**, never a side effect of a missing file. It is
allowed only when the database has *no encrypted state at all* — a restored
database with encrypted rows but no key is an EXISTING install with lost
keys and must fail loud, not bootstrap (M4.11-FR-012). ``force`` does not
override that check; nothing does.

Entry points:
- ``python -m app.security.keys bootstrap`` (operator command)
- ``verify_key_material(db, allow_bootstrap=True)`` on a NEW install when
  ``ENCRYPTION_KEY_ALLOW_BOOTSTRAP`` is set (container first-run convenience)
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.security.canary import write_canary
from app.security.encryption_provider import get_encryption_key_provider
from app.security.errors import KeyMaterialError
from app.security.install_mode import InstallMode, detect_install_mode


@dataclass(frozen=True)
class BootstrapResult:
    encryption_fingerprint: str
    encryption_provider: str
    signing_key_id: str
    signing_key_version: int
    signing_public_key_fingerprint: str


def bootstrap_key_material(db: Session) -> BootstrapResult:
    """Provision fresh encryption + signing key material for a genuinely new
    installation. Raises ``KeyMaterialError`` if the database already holds
    encrypted or signed state, or if key material is already present."""
    report = detect_install_mode(db)
    if report.mode is not InstallMode.NEW:
        raise KeyMaterialError(
            "BOOTSTRAP_REFUSED_EXISTING_INSTALL",
            (
                "the database already holds encrypted or signed state ("
                + ", ".join(report.encrypted_state_tables + report.signed_state_tables)
                + ") — this is an existing installation, not a new one"
            ),
            remediation=(
                "restore the original key material from the recovery archive (see "
                "docs/security/key-management.md); bootstrapping here would orphan every existing "
                "secret and signature"
            ),
        )

    enc_provider = get_encryption_key_provider()
    if enc_provider.is_present():
        raise KeyMaterialError(
            "BOOTSTRAP_REFUSED_KEY_PRESENT",
            "an encryption key is already configured or present",
            remediation="the existing key must not be replaced; remove --force expectations, nothing overrides this",
        )
    enc_provider.bootstrap()
    enc_provider = get_encryption_key_provider()  # re-read now that the file exists
    write_canary(db, enc_provider)

    # Signing: provision the default identity so the first publish does not
    # implicitly bootstrap it either.
    from app.runtime.versioning.keys import SigningKeyService

    signing_key = SigningKeyService(db).ensure_key(settings.SIGNING_DEFAULT_KEY_ID)

    from app.runtime.versioning.signing.local import LocalKeyProvider
    from app.runtime.versioning.signing.registry import get_signing_provider

    provider = get_signing_provider()
    pub_fp = "n/a"
    if isinstance(provider, LocalKeyProvider):
        from app.security.encryption_provider import key_fingerprint

        pub_fp = key_fingerprint(provider.get_public_key(signing_key.key_id, signing_key.current_version))

    return BootstrapResult(
        encryption_fingerprint=enc_provider.fingerprint(),
        encryption_provider=enc_provider.name,
        signing_key_id=signing_key.key_id,
        signing_key_version=signing_key.current_version,
        signing_public_key_fingerprint=pub_fp,
    )
