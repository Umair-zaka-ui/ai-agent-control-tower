"""Phase M4.11 / M4.11a — the deliberate new-install bootstrap.

Bootstrap is **explicit**, never a side effect of a missing file. It is
allowed only when this installation is classified NEW — which, since Phase
M4.11a, means **the durable ``installation_bootstrap`` marker is absent AND
there is no encrypted or signed state**. A restored/cloned database carries
the marker, so it is always EXISTING and bootstrap refuses it — even if its
ciphertext tables happened to be empty at backup time.

A deliberate bootstrap:
- provisions the encryption key (or *adopts* an operator-provided one),
- writes the key-validation canary,
- provisions the default signing identity,
- and records the durable bootstrap marker — atomically enough that a
  half-completed bootstrap (key without marker) is detected and fails loud
  at the next startup.

Entry points: ``python -m app.security.keys bootstrap`` (operator command),
or ``verify_key_material(db, allow_bootstrap=True)`` on a NEW install when
``ENCRYPTION_KEY_ALLOW_BOOTSTRAP`` is set (container first-run convenience).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.security.canary import write_canary
from app.security.encryption_provider import get_encryption_key_provider
from app.security.errors import KeyMaterialError
from app.security.install_mode import InstallMode, detect_install_mode
from app.security.installation import record_bootstrap


@dataclass(frozen=True)
class BootstrapResult:
    encryption_fingerprint: str
    encryption_provider: str
    adopted_existing_key: bool
    signing_key_id: str
    signing_key_version: int
    signing_public_key_fingerprint: str


def bootstrap_key_material(db: Session) -> BootstrapResult:
    """Provision (or adopt) key material for a genuinely new installation and
    record the durable bootstrap marker. Raises ``KeyMaterialError`` if this
    installation is classified EXISTING (marker present, or any encrypted /
    signed state)."""
    report = detect_install_mode(db)
    if report.mode is not InstallMode.NEW:
        code = "BOOTSTRAP_REFUSED_MARKER_PRESENT" if report.bootstrap_marker else "BOOTSTRAP_REFUSED_EXISTING_INSTALL"
        raise KeyMaterialError(
            code,
            f"this installation is already established ({report.reason}) — it is not a new one",
            remediation=(
                "restore the original key material from the recovery archive (see "
                "docs/security/key-management.md); bootstrapping here would orphan every existing "
                "secret and signature"
            ),
        )

    enc_provider = get_encryption_key_provider()
    adopted = enc_provider.is_present()
    if not adopted:
        enc_provider.bootstrap()
        enc_provider = get_encryption_key_provider()  # re-read now that the file exists
    write_canary(db, enc_provider)
    record_bootstrap(db, enc_provider, recorded_via="bootstrap")

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
        adopted_existing_key=adopted,
        signing_key_id=signing_key.key_id,
        signing_key_version=signing_key.current_version,
        signing_public_key_fingerprint=pub_fp,
    )
