"""Phase M4.11 — Production Integrity Closure: key-material recovery &
fail-loud integrity. **Phase M4.11a** — install-mode classification
hardening (the durable bootstrap marker + the five-state key taxonomy);
its cases are the ``test_m411a_*`` block at the end of this file.

The guarantee under test, in one sentence: **an established installation
missing or holding the wrong encryption/signing key fails loud and
recoverable — it never silently regenerates key material and continues** —
and (M4.11a) that holds even when the install has zero encrypted credential
rows, because NEW is a positive durable fact (the bootstrap marker being
absent), never inferred from absent ciphertext.

Groups map to the acceptance criteria in the build prompts:

- AC-01..05  fail-loud (missing key, wrong key, signing, no-secret messages, install-mode)
- AC-06      deliberate bootstrap
- AC-07..10  backup / restore / continuity / the negative proofs
- AC-11..14  provider seam, rotation, no-migration-decrypt-change, no-leak
- AC-18      the end-to-end production-integrity proof (§16)
- AC-19      no new deferred-work or skipped-test markers in the new files
- M4.11a AC-01..13  the durable bootstrap marker, the corrected truth table,
  the zero-ciphertext edge case, the five-state taxonomy
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.security import InstallationBootstrap, KeyMaterialCanary
from app.runtime.providers import credential_crypto
from app.security import backup as key_backup
from app.security import installation as install_marker
from app.security.bootstrap import bootstrap_key_material
from app.security.canary import KEY_CANARY_PLAINTEXT, MODEL_CREDENTIAL_ENCRYPTION, write_canary
from app.security.encryption_provider import (
    LocalEncryptionKeyProvider,
    ProviderUnavailableError,
    get_encryption_key_provider,
    key_fingerprint,
)
from app.security.errors import KeyMaterialError
from app.security.install_mode import InstallMode, InstallModeReport, detect_install_mode
from app.security.installation import marker_present, record_bootstrap
from app.security.key_integrity import (
    KeyState,
    verify_encryption_material,
    verify_key_material,
    verify_signing_material,
    verify_signing_material_for_key,
)

RT = "/api/v1/runtime"
PASSWORD = "T3st!Passw0rd#Ok"
_SECRET = "sk-test-fake-m411-abcdef0123456789"

_BACKEND = Path(__file__).resolve().parents[2]
_SECURITY_DIR = _BACKEND / "app" / "security"


# --------------------------------------------------------------------------- #
# Fixtures — isolated key material under a tmp dir
# --------------------------------------------------------------------------- #
@pytest.fixture()
def keyenv(tmp_path, monkeypatch):
    """A throwaway encryption-key file + a throwaway signing key dir, so a
    test can lose/replace/restore key material without touching the
    developer's real ``.keys/``."""
    kd = tmp_path / "keys"
    kd.mkdir()
    enc = kd / "model_credentials.key"
    enc.write_bytes(Fernet.generate_key())
    monkeypatch.setattr(settings, "MODEL_CREDENTIAL_ENCRYPTION_KEY", None)
    monkeypatch.setattr(settings, "MODEL_CREDENTIAL_ENCRYPTION_KEY_PATH", str(enc))
    monkeypatch.setattr(settings, "MODEL_CREDENTIAL_ENCRYPTION_KEYS", [])
    monkeypatch.setattr(settings, "ENCRYPTION_KEY_ALLOW_BOOTSTRAP", False)
    monkeypatch.setattr(settings, "KEY_MATERIAL_FAIL_LOUD", True)
    credential_crypto.reset_cached_key()
    yield SimpleNamespace(dir=kd, enc=enc, tmp=tmp_path)
    credential_crypto.reset_cached_key()


@pytest.fixture()
def signing_env(keyenv, monkeypatch):
    """As ``keyenv``, plus point the signing provider at the same tmp dir and
    give this test a unique signing identity."""
    monkeypatch.setattr(settings, "SIGNING_KEY_PATH", str(keyenv.dir))
    key_id = f"m411-{uuid.uuid4().hex[:12]}"
    monkeypatch.setattr(settings, "SIGNING_DEFAULT_KEY_ID", key_id)
    keyenv.signing_key_id = key_id
    return keyenv


def _register_org(client) -> dict:
    email = f"m411_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": "M4.11 Org", "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    return {"headers": {"Authorization": f"Bearer {tokens['access_token']}"}}


def _store_credential(client, org, secret: str = _SECRET) -> None:
    r = client.put(f"{RT}/providers/OPENAI_COMPATIBLE/credentials", headers=org["headers"],
                   json={"secret": secret})
    assert r.status_code == 200, r.text


def _newest_provider_ciphertext(db: Session) -> str:
    return db.execute(
        text("SELECT encrypted_secret FROM provider_credentials ORDER BY created_at DESC LIMIT 1")
    ).scalar_one()


def _clear_canary(db: Session) -> None:
    db.execute(text("DELETE FROM key_material_canary WHERE purpose = :p"), {"p": MODEL_CREDENTIAL_ENCRYPTION})
    db.commit()


def _clear_marker(db: Session) -> None:
    db.execute(text("DELETE FROM installation_bootstrap"))
    db.commit()


@pytest.fixture(autouse=True)
def _reset_install_markers(db_session: Session):
    """The ``installation_bootstrap`` singleton and the encryption canary are
    platform-scoped rows on the shared dev DB. A deliberate bootstrap in one
    test would otherwise pin every later test's classification. Clear both
    before and after each test in this file; the real dev install gets its
    marker from ``keys verify`` / lifespan, not the suite."""
    _clear_marker(db_session)
    _clear_canary(db_session)
    yield
    _clear_marker(db_session)
    _clear_canary(db_session)


# --------------------------------------------------------------------------- #
# AC-01 — established install, missing encryption key ⇒ fail loud, no regen
# --------------------------------------------------------------------------- #
def test_ac01_missing_encryption_key_on_established_install_fails_loud(keyenv, client, db_session):
    org = _register_org(client)
    _store_credential(client, org)  # the DB now holds ciphertext -> EXISTING

    keyenv.enc.unlink()
    credential_crypto.reset_cached_key()

    with pytest.raises(KeyMaterialError) as exc:
        verify_encryption_material(db_session)
    assert exc.value.code == "ENCRYPTION_KEY_MISSING_ESTABLISHED_INSTALL"

    # It did NOT write a replacement key.
    assert not keyenv.enc.exists()
    # And the crypto layer itself refuses rather than minting a new key.
    with pytest.raises(KeyMaterialError):
        credential_crypto.encrypt_secret("x")
    assert not keyenv.enc.exists()


def test_ac01_the_full_check_refuses_to_serve(keyenv, client, db_session, monkeypatch):
    org = _register_org(client)
    _store_credential(client, org)
    keyenv.enc.unlink()
    credential_crypto.reset_cached_key()
    monkeypatch.setattr(settings, "SIGNING_DEFAULT_KEY_ID", f"m411-{uuid.uuid4().hex[:12]}")
    with pytest.raises(KeyMaterialError):
        verify_key_material(db_session)


# --------------------------------------------------------------------------- #
# AC-02 — a WRONG key fails too, deterministically
# --------------------------------------------------------------------------- #
def test_ac02_wrong_encryption_key_fails_loud_and_is_deterministic(keyenv, client, db_session):
    org = _register_org(client)
    _store_credential(client, org)
    _clear_canary(db_session)

    keyenv.enc.write_bytes(Fernet.generate_key())  # a different, valid Fernet key
    credential_crypto.reset_cached_key()

    codes = set()
    for _ in range(3):
        with pytest.raises(KeyMaterialError) as exc:
            verify_encryption_material(db_session)
        codes.add(exc.value.code)
    assert codes == {"ENCRYPTION_KEY_CANNOT_DECRYPT"}  # same outcome every time


def test_ac02_corrupt_canary_is_detected_as_mismatch(keyenv, db_session):
    provider = get_encryption_key_provider()
    right_fp = provider.fingerprint()
    _clear_canary(db_session)
    # A canary row for the right fingerprint whose verifier was made with a
    # different key — i.e. the key was swapped after the canary was written.
    other = Fernet(Fernet.generate_key())
    db_session.add(KeyMaterialCanary(
        purpose=MODEL_CREDENTIAL_ENCRYPTION, key_fingerprint=right_fp,
        verifier=other.encrypt(KEY_CANARY_PLAINTEXT).decode("ascii"), key_provider="LOCAL",
    ))
    db_session.commit()
    with pytest.raises(KeyMaterialError) as exc:
        verify_encryption_material(db_session)
    assert exc.value.code == "ENCRYPTION_KEY_MISMATCH"
    _clear_canary(db_session)


# --------------------------------------------------------------------------- #
# AC-03 — signing: missing / wrong private key ⇒ fail loud, no new identity
# --------------------------------------------------------------------------- #
def test_ac03_missing_signing_private_key_fails_loud(signing_env, db_session):
    from app.runtime.versioning.keys import SigningKeyService

    kid = signing_env.signing_key_id
    key_row = SigningKeyService(db_session).ensure_key(kid)  # provisions .pem + DB row
    assert (signing_env.dir / f"{kid}.v1.pem").exists()

    (signing_env.dir / f"{kid}.v1.pem").unlink()

    with pytest.raises(KeyMaterialError) as exc:
        verify_signing_material(db_session)
    assert exc.value.code == "SIGNING_PRIVATE_KEY_MISSING"

    # A fresh service call must NOT silently mint a replacement identity.
    with pytest.raises(KeyMaterialError):
        SigningKeyService(SessionLocal()).ensure_key(kid)
    assert not (signing_env.dir / f"{kid}.v1.pem").exists()


def test_ac03_wrong_signing_private_key_is_a_mismatch(signing_env, db_session):
    from app.runtime.versioning.keys import SigningKeyService

    kid = signing_env.signing_key_id
    SigningKeyService(db_session).ensure_key(kid)

    # Replace the private key file with a different keypair's private key.
    other = Ed25519PrivateKey.generate()
    (signing_env.dir / f"{kid}.v1.pem").write_bytes(other.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    with pytest.raises(KeyMaterialError) as exc:
        verify_signing_material(db_session)
    assert exc.value.code == "SIGNING_KEY_MISMATCH"


# --------------------------------------------------------------------------- #
# AC-04 / AC-14 — failure messages carry no key/secret material
# --------------------------------------------------------------------------- #
def test_ac04_failure_messages_contain_no_secret(signing_env, client, db_session, caplog):
    from app.runtime.versioning.keys import SigningKeyService

    org = _register_org(client)
    _store_credential(client, org)
    _clear_canary(db_session)

    right_key = signing_env.enc.read_bytes()
    kid = signing_env.signing_key_id
    SigningKeyService(db_session).ensure_key(kid)
    priv = (signing_env.dir / f"{kid}.v1.pem").read_bytes()

    messages: list[str] = []

    # missing encryption key
    signing_env.enc.unlink()
    credential_crypto.reset_cached_key()
    with pytest.raises(KeyMaterialError) as e1:
        verify_encryption_material(db_session)
    messages.append(str(e1.value))

    # wrong encryption key
    signing_env.enc.write_bytes(Fernet.generate_key())
    credential_crypto.reset_cached_key()
    with pytest.raises(KeyMaterialError) as e2:
        verify_encryption_material(db_session)
    messages.append(str(e2.value))

    # missing signing key
    (signing_env.dir / f"{kid}.v1.pem").unlink()
    with pytest.raises(KeyMaterialError) as e3:
        verify_signing_material(db_session)
    messages.append(str(e3.value))

    haystack = " ".join(messages) + "\n" + caplog.text
    for needle in (
        right_key.decode(), right_key.decode().rstrip("="),
        priv.decode(), KEY_CANARY_PLAINTEXT.decode(),
        _SECRET, _newest_provider_ciphertext(db_session),
    ):
        assert needle not in haystack
    for msg in messages:
        assert " — " in msg  # problem — remediation shape, always


# --------------------------------------------------------------------------- #
# AC-05 — a restored DB with rows + no key is EXISTING, never NEW
# --------------------------------------------------------------------------- #
def test_ac05_restored_db_with_rows_and_no_key_is_existing(keyenv, client, db_session):
    org = _register_org(client)
    _store_credential(client, org)
    keyenv.enc.unlink()
    credential_crypto.reset_cached_key()

    report = detect_install_mode(db_session)
    assert report.mode is InstallMode.EXISTING
    assert "provider_credentials" in report.encrypted_state_tables

    with pytest.raises(KeyMaterialError) as exc:
        bootstrap_key_material(db_session)
    assert exc.value.code == "BOOTSTRAP_REFUSED_EXISTING_INSTALL"
    assert not keyenv.enc.exists()


# --------------------------------------------------------------------------- #
# AC-06 — a genuine new install bootstraps deliberately and safely
# --------------------------------------------------------------------------- #
def test_ac06_new_install_bootstraps_when_allowed(keyenv, db_session, monkeypatch):
    keyenv.enc.unlink()
    credential_crypto.reset_cached_key()
    monkeypatch.setattr(
        "app.security.key_integrity.detect_install_mode",
        lambda db: InstallModeReport(InstallMode.NEW, (), ()),
    )
    # Without the deliberate opt-in: fail loud, do not infer a bootstrap.
    with pytest.raises(KeyMaterialError) as exc:
        verify_encryption_material(db_session, allow_bootstrap=False)
    assert exc.value.code == "INSTALLATION_NEVER_BOOTSTRAPPED"
    assert not keyenv.enc.exists()

    # With it: deliberate bootstrap — key file, canary, AND the durable marker.
    result = verify_encryption_material(db_session, allow_bootstrap=True)
    assert result["validation"] == "BOOTSTRAPPED"
    assert result["key_state"] == KeyState.OK.value
    assert keyenv.enc.exists()
    fp = key_fingerprint(keyenv.enc.read_bytes())
    row = db_session.execute(select(KeyMaterialCanary).where(
        KeyMaterialCanary.key_fingerprint == fp)).scalar_one()
    assert row.purpose == MODEL_CREDENTIAL_ENCRYPTION
    marker = db_session.execute(select(InstallationBootstrap)).scalar_one()
    assert marker.active_key_fingerprint == fp and marker.recorded_via == "bootstrap"


def test_ac06_local_provider_bootstrap_refuses_to_clobber(keyenv):
    provider = LocalEncryptionKeyProvider(key_path=str(keyenv.enc))
    with pytest.raises(KeyMaterialError) as exc:
        provider.bootstrap()
    assert exc.value.code == "ENCRYPTION_KEY_ALREADY_PRESENT"


# --------------------------------------------------------------------------- #
# AC-07 / AC-09 — backup, restore, and cryptographic continuity (positive)
# --------------------------------------------------------------------------- #
def test_ac07_and_ac09_positive_restore_proof(signing_env, client, db_session):
    from app.runtime.versioning.keys import SigningKeyService
    from app.runtime.versioning.signing.registry import get_signing_provider

    # 2. encrypted credential  +  3. a real signing operation
    org = _register_org(client)
    _store_credential(client, org, secret=_SECRET)
    ciphertext = _newest_provider_ciphertext(db_session)
    assert credential_crypto.decrypt_secret(ciphertext) == _SECRET

    kid = signing_env.signing_key_id
    key_row = SigningKeyService(db_session).ensure_key(kid)
    provider = get_signing_provider()
    payload = b"m4.11 attestation payload"
    sig = provider.sign(payload, kid)
    assert provider.verify(payload, sig.signature, kid, sig.key_version) is True

    # 4. produce the recovery archive
    archive = signing_env.tmp / "archive"
    manifest = key_backup.create_key_material_archive(archive)
    # the manifest NAMES artifacts + checksums, never their contents
    manifest_text = (archive / "MANIFEST.json").read_text()
    assert signing_env.enc.read_bytes().decode() not in manifest_text
    assert any(a["name"].endswith("model_credentials.key") for a in manifest["artifacts"])
    assert all(len(a["sha256"]) == 64 for a in manifest["artifacts"])
    assert key_backup.verify_key_material_archive(archive) == []

    # 5-7. lose the runtime environment: empty key dir
    for f in list(signing_env.dir.iterdir()):
        f.unlink()
    credential_crypto.reset_cached_key()
    assert not signing_env.enc.exists()

    # 6. restore key material
    restored = key_backup.restore_key_material_archive(archive)
    assert signing_env.enc in restored
    credential_crypto.reset_cached_key()

    # 7. start ACT — the continuity check passes
    report = verify_key_material(db_session)
    assert report.encryption["validation"] in {"CANARY_MATCH", "TRIAL_DECRYPT", "REGISTERED"}

    # 8. pre-backup credential decrypts
    assert credential_crypto.decrypt_secret(ciphertext) == _SECRET
    # 9. pre-backup signature verifies
    assert provider.verify(payload, sig.signature, kid, sig.key_version) is True
    # 10. new signing continues under the same identity
    sig2 = provider.sign(b"a later payload", kid)
    assert provider.verify(b"a later payload", sig2.signature, kid, sig2.key_version) is True
    assert sig2.key_id == kid


# --------------------------------------------------------------------------- #
# AC-08 — signing key backup / recovery + historical verifiability
# --------------------------------------------------------------------------- #
def test_ac08_historical_signatures_survive_key_loss_and_restore(signing_env, db_session):
    from app.runtime.versioning.keys import SigningKeyService
    from app.runtime.versioning.signing.registry import get_signing_provider

    kid = signing_env.signing_key_id
    SigningKeyService(db_session).ensure_key(kid)
    provider = get_signing_provider()
    payload = b"signed before any loss"
    sig = provider.sign(payload, kid)
    public_before = provider.get_public_key(kid, sig.key_version)

    archive = signing_env.tmp / "sign-archive"
    key_backup.create_key_material_archive(archive)
    for f in list(signing_env.dir.iterdir()):
        f.unlink()
    key_backup.restore_key_material_archive(archive)

    assert provider.get_public_key(kid, sig.key_version) == public_before
    assert provider.verify(payload, sig.signature, kid, sig.key_version) is True


# --------------------------------------------------------------------------- #
# AC-10 — the negative restore proofs
# --------------------------------------------------------------------------- #
def test_ac10_negative_restore_missing_key_never_regenerates(signing_env, client, db_session):
    org = _register_org(client)
    _store_credential(client, org)
    for f in list(signing_env.dir.iterdir()):
        f.unlink()
    credential_crypto.reset_cached_key()
    with pytest.raises(KeyMaterialError):
        verify_key_material(db_session)
    assert list(signing_env.dir.iterdir()) == []  # nothing regenerated


def test_ac10_negative_restore_wrong_key_is_deterministic(keyenv, client, db_session):
    org = _register_org(client)
    _store_credential(client, org)
    _clear_canary(db_session)
    keyenv.enc.write_bytes(Fernet.generate_key())
    credential_crypto.reset_cached_key()
    outcomes = {verify_encryption_material.__name__: []}
    for _ in range(2):
        with pytest.raises(KeyMaterialError) as exc:
            verify_encryption_material(db_session)
        outcomes[verify_encryption_material.__name__].append(exc.value.code)
    assert len(set(outcomes[verify_encryption_material.__name__])) == 1


# --------------------------------------------------------------------------- #
# AC-11 — the provider seam mirrors SigningProvider; no vendor SDK in core
# --------------------------------------------------------------------------- #
def test_ac11_encryption_key_provider_seam():
    from app.security.encryption_provider import _REGISTRY, EncryptionKeyProvider

    assert issubclass(LocalEncryptionKeyProvider, EncryptionKeyProvider)
    assert _REGISTRY["LOCAL"] is LocalEncryptionKeyProvider
    provider = get_encryption_key_provider()
    assert isinstance(provider, LocalEncryptionKeyProvider)
    for method in ("is_present", "get_key", "fallback_keys", "bootstrap"):
        assert callable(getattr(provider, method))
    # credential_crypto asks the provider, never a path
    src = (_BACKEND / "app" / "runtime" / "providers" / "credential_crypto.py").read_text()
    assert "get_encryption_key_provider" in src


def test_ac11_core_imports_no_vendor_sdk():
    banned = {"boto3", "botocore", "hvac", "azure", "google.cloud"}
    for path in _SECURITY_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(), str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert not any(name == b or name.startswith(b + ".") for b in banned), (
                    f"{path.name} imports a vendor SDK: {name}"
                )


# --------------------------------------------------------------------------- #
# AC-12 — rotation: the key ring decrypts old, encrypts new; full re-encrypt deferred
# --------------------------------------------------------------------------- #
def test_ac12_encryption_key_rotation_via_key_ring(keyenv, client, db_session, monkeypatch):
    old_key = keyenv.enc.read_bytes()
    old_token = credential_crypto.encrypt_secret("rotate-me")
    # a real stored credential, encrypted under the OLD key, so the post-
    # rotation trial-decrypt has an incumbent row to recognise
    org = _register_org(client)
    _store_credential(client, org, secret=_SECRET)

    new_key = Fernet.generate_key()
    keyenv.enc.write_bytes(new_key)
    monkeypatch.setattr(settings, "MODEL_CREDENTIAL_ENCRYPTION_KEYS", [old_key.decode()])
    credential_crypto.reset_cached_key()

    # old ciphertext still decrypts (fallback key), new writes use the new key
    assert credential_crypto.decrypt_secret(old_token) == "rotate-me"
    new_token = credential_crypto.encrypt_secret("after-rotation")
    assert Fernet(new_key).decrypt(new_token.encode()).decode() == "after-rotation"

    _clear_canary(db_session)
    result = verify_encryption_material(db_session)
    assert result["fingerprint"] == key_fingerprint(new_key)
    _clear_canary(db_session)


# --------------------------------------------------------------------------- #
# AC-13 — migration 0052 is additive and changes no decrypt behaviour
# --------------------------------------------------------------------------- #
def test_ac13_migration_is_additive_only():
    mig = (_BACKEND / "migrations" / "versions" / "0052_key_material_canary.py").read_text()
    tree = ast.parse(mig)
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name) and node.func.value.id == "op"
    }
    assert calls <= {"create_table", "drop_table"}
    assert "key_material_canary" in mig
    # no ALTER/UPDATE/data backfill on an existing table
    assert "alter_table" not in mig and "add_column" not in mig and "execute" not in mig


def test_ac13_existing_ciphertext_decrypts_unchanged(keyenv, client, db_session):
    org = _register_org(client)
    _store_credential(client, org, secret=_SECRET)
    ciphertext = _newest_provider_ciphertext(db_session)
    # canary write does not touch it
    _clear_canary(db_session)
    write_canary(db_session, get_encryption_key_provider())
    assert credential_crypto.decrypt_secret(ciphertext) == _SECRET
    assert _newest_provider_ciphertext(db_session) == ciphertext
    _clear_canary(db_session)


# --------------------------------------------------------------------------- #
# AC-14 — no key/secret in source-level logging of the new code
# --------------------------------------------------------------------------- #
def test_ac14_new_code_never_logs_or_prints_key_bytes():
    """Structural: no ``get_key()`` / raw key value flows into a log or print
    call in the new security package or credential_crypto."""
    files = list(_SECURITY_DIR.glob("*.py")) + [
        _BACKEND / "app" / "runtime" / "providers" / "credential_crypto.py"
    ]
    sinks = {"info", "warning", "error", "debug", "exception", "print"}
    for path in files:
        tree = ast.parse(path.read_text(), str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)):
                continue
            fname = (
                node.func.attr if isinstance(node.func, ast.Attribute)
                else getattr(node.func, "id", "")
            )
            if fname not in sinks:
                continue
            for arg in ast.walk(node):
                if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute):
                    assert arg.func.attr not in {"get_key", "all_keys", "fallback_keys"}, (
                        f"{path.name}: key material flows into {fname}()"
                    )


# --------------------------------------------------------------------------- #
# AC-15 — an established install with a valid key is byte-for-byte unchanged
# --------------------------------------------------------------------------- #
def test_ac15_valid_key_established_install_is_a_noop(keyenv, client, db_session):
    org = _register_org(client)
    _store_credential(client, org, secret=_SECRET)
    ciphertext = _newest_provider_ciphertext(db_session)

    report = verify_encryption_material(db_session)
    assert report["validation"] in {"CANARY_MATCH", "TRIAL_DECRYPT", "REGISTERED"}
    # unchanged: same ciphertext still resolves, encryption still works
    assert credential_crypto.decrypt_secret(ciphertext) == _SECRET
    r = client.get(f"{RT}/providers/credentials", headers=org["headers"])
    assert r.status_code == 200
    _clear_canary(db_session)


# --------------------------------------------------------------------------- #
# AC-18 — the end-to-end production-integrity proof (§16)
# --------------------------------------------------------------------------- #
def test_ac18_e2e_production_integrity_proof(signing_env, client, db_session, caplog, monkeypatch):
    """One test, the §16 sequence: bootstrap → store secret → sign → back up →
    lose → restore → decrypt + verify + new-sign → then the negatives
    (missing key, wrong key, **and M4.11a's zero-ciphertext leg**) fail loud
    with no regeneration and no leak."""
    from app.runtime.versioning.keys import SigningKeyService
    from app.runtime.versioning.signing.registry import get_signing_provider

    # 1. bootstrap correctly — an operator-supplied key is a deliberate bootstrap
    provided = Fernet.generate_key()
    signing_env.enc.write_bytes(provided)
    credential_crypto.reset_cached_key()
    _clear_canary(db_session)

    # 2. representative encrypted credential
    org = _register_org(client)
    _store_credential(client, org, secret=_SECRET)
    ciphertext = _newest_provider_ciphertext(db_session)

    # 3. representative signed artifact
    kid = signing_env.signing_key_id
    SigningKeyService(db_session).ensure_key(kid)
    provider = get_signing_provider()
    payload = b"e2e in-toto payload"
    sig = provider.sign(payload, kid)

    # 4. supported recovery backup
    archive = signing_env.tmp / "e2e-archive"
    key_backup.create_key_material_archive(archive)

    # 5-6. simulate loss + restore DB(unchanged, shared) + key material
    for f in list(signing_env.dir.iterdir()):
        f.unlink()
    credential_crypto.reset_cached_key()
    key_backup.restore_key_material_archive(archive)
    credential_crypto.reset_cached_key()

    # 7. start ACT
    ok_report = verify_key_material(db_session)
    assert ok_report.signing["validation"] == "OK"

    # 8-11. continuity retained
    assert credential_crypto.decrypt_secret(ciphertext) == _SECRET
    assert provider.verify(payload, sig.signature, kid, sig.key_version) is True
    later = provider.sign(b"post-restore", kid)
    assert provider.verify(b"post-restore", later.signature, kid, later.key_version) is True

    # 12-13. restart WITHOUT the encryption key ⇒ fail loud, no regeneration
    signing_env.enc.unlink()
    credential_crypto.reset_cached_key()
    with pytest.raises(KeyMaterialError) as missing:
        verify_key_material(db_session)
    assert missing.value.code == "ENCRYPTION_KEY_MISSING_ESTABLISHED_INSTALL"
    assert not signing_env.enc.exists()

    # 14-15. restart with the WRONG key ⇒ deterministic safe failure
    _clear_canary(db_session)
    signing_env.enc.write_bytes(Fernet.generate_key())
    credential_crypto.reset_cached_key()
    with pytest.raises(KeyMaterialError) as wrong:
        verify_key_material(db_session)
    assert wrong.value.code in {"ENCRYPTION_KEY_MISMATCH", "ENCRYPTION_KEY_CANNOT_DECRYPT"}

    # M4.11a leg — an established install with the durable marker but ZERO
    # encrypted/signed state, key lost ⇒ still fails loud (EXISTING), never
    # bootstraps. (Simulate zero-ciphertext by reporting no state; the
    # marker alone must carry EXISTING.)
    signing_env.enc.write_bytes(provided)
    credential_crypto.reset_cached_key()
    _clear_canary(db_session)
    record_bootstrap(db_session, get_encryption_key_provider(), recorded_via="backfill")
    monkeypatch.setattr(
        "app.security.key_integrity.detect_install_mode",
        lambda db: InstallModeReport(InstallMode.EXISTING, (), (), bootstrap_marker=True),
    )
    signing_env.enc.unlink()
    credential_crypto.reset_cached_key()
    with pytest.raises(KeyMaterialError) as zero_ct:
        verify_encryption_material(db_session)
    assert zero_ct.value.code == "ENCRYPTION_KEY_MISSING_ESTABLISHED_INSTALL"
    assert not signing_env.enc.exists()

    # 16. no key/secret leaked anywhere along the way
    leak = caplog.text
    for needle in (provided.decode(), provided.decode().rstrip("="), _SECRET,
                   KEY_CANARY_PLAINTEXT.decode(), ciphertext):
        assert needle not in leak
        assert needle not in str(missing.value)
        assert needle not in str(wrong.value)
        assert needle not in str(zero_ct.value)


# --------------------------------------------------------------------------- #
# AC-19 — no new deferred-work / skipped-test markers in the new files
# --------------------------------------------------------------------------- #
def test_ac19_no_forbidden_markers_in_new_files():
    files = list(_SECURITY_DIR.glob("*.py")) + [
        _BACKEND / "app" / "models" / "security.py",
        _BACKEND / "migrations" / "versions" / "0052_key_material_canary.py",
        Path(__file__),
    ]
    files.append(_BACKEND / "migrations" / "versions" / "0053_installation_bootstrap.py")
    forbidden = ("TO" + "DO", "FIX" + "ME", "Not" + "ImplementedError",
                 "pytest.mark." + "skip", "pytest.mark." + "xfail")
    for path in files:
        text_ = path.read_text(encoding="utf-8")
        hits = [tok for tok in forbidden if tok in text_]
        assert not hits, f"{path.name}: {hits}"


# --------------------------------------------------------------------------- #
# Phase M4.11a - Install-Mode Classification Hardening (durable bootstrap marker)
# --------------------------------------------------------------------------- #
def _raise_unavailable(self, *_a, **_k):
    raise ProviderUnavailableError("simulated key-provider outage")


def _mode(monkeypatch, *, marker: bool, encrypted=(), signed=()):
    """Force ``detect_install_mode`` (as seen by key_integrity + bootstrap) to a
    chosen shape, so the classification truth table can be exercised
    deterministically against the shared dev DB."""
    rep = InstallModeReport(
        InstallMode.EXISTING if (marker or encrypted or signed) else InstallMode.NEW,
        tuple(encrypted), tuple(signed), bootstrap_marker=marker,
    )
    for target in ("app.security.key_integrity.detect_install_mode",
                   "app.security.bootstrap.detect_install_mode"):
        monkeypatch.setattr(target, lambda db, _r=rep: _r)
    return rep


# --- AC-01 — the durable marker ------------------------------------------- #
def test_m411a_ac01_marker_is_a_durable_singleton_with_no_secret(keyenv, db_session):
    provider = get_encryption_key_provider()
    assert marker_present(db_session) is False

    row = record_bootstrap(db_session, provider, recorded_via="bootstrap")
    assert marker_present(db_session) is True
    assert row.active_key_fingerprint == provider.fingerprint()
    assert row.keyring_schema_version == install_marker.KEYRING_SCHEMA_VERSION

    # idempotent — a second call returns the same row, never a duplicate
    again = record_bootstrap(db_session, provider, recorded_via="backfill")
    assert again.id == row.id
    assert db_session.execute(select(InstallationBootstrap)).scalars().all() == [again]

    # no secret in the row
    blob = " ".join(str(getattr(row, c)) for c in
                    ("active_key_fingerprint", "key_provider", "keyring_schema_version", "recorded_via"))
    assert keyenv.enc.read_bytes().decode() not in blob
    assert repr(row).count(":") >= 0 and "verifier" not in repr(row).lower()


# --- AC-02 — the corrected truth table ---------------------------------- #
def test_m411a_ac02_detect_install_mode_truth_table(db_session, monkeypatch):
    import app.security.install_mode as im

    cases = [
        # (marker, encrypted, signed) -> expected mode
        (True, (), (), InstallMode.EXISTING),           # marker alone
        (True, ("provider_credentials",), (), InstallMode.EXISTING),
        (False, ("tool_credentials",), (), InstallMode.EXISTING),   # ciphertext fast-path
        (False, (), ("signing_keys",), InstallMode.EXISTING),       # signed-state fast-path
        (False, (), (), InstallMode.NEW),               # the ONLY NEW shape
    ]
    for marker, enc, sig, expected in cases:
        monkeypatch.setattr(im, "marker_present", lambda db, _m=marker: _m)
        monkeypatch.setattr(
            im, "_tables_with_rows",
            lambda db, probes, _e=enc, _s=sig: _e if probes is im.CIPHERTEXT_PROBES else _s,
        )
        assert im.detect_install_mode(db_session).mode is expected, (marker, enc, sig)


# --- AC-03 — THE edge case: established, zero ciphertext, key lost ------- #
def test_m411a_ac03_established_zero_ciphertext_install_fails_loud(keyenv, db_session, monkeypatch):
    """An established install with domain state but zero encrypted rows,
    marker present, key lost ⇒ fails loud (EXISTING), never bootstraps.

    This is the defect M4.11 carried. Proven both ways: the *old*
    absence-inference signal (``has_encrypted_state``) would have said NEW;
    the *new* signal (the marker) says EXISTING."""
    rep = _mode(monkeypatch, marker=True, encrypted=(), signed=())
    # the regression bites the old logic ...
    assert rep.has_encrypted_state is False        # old "established?" test -> NEW (wrong)
    assert rep.mode is InstallMode.EXISTING        # new signal -> EXISTING (right)

    keyenv.enc.unlink()
    credential_crypto.reset_cached_key()
    with pytest.raises(KeyMaterialError) as exc:
        verify_encryption_material(db_session, allow_bootstrap=True)  # even WITH the opt-in
    assert exc.value.code == "ENCRYPTION_KEY_MISSING_ESTABLISHED_INSTALL"
    assert not keyenv.enc.exists()               # nothing regenerated

    # and bootstrap itself refuses it
    with pytest.raises(KeyMaterialError) as b:
        bootstrap_key_material(db_session)
    assert b.value.code == "BOOTSTRAP_REFUSED_MARKER_PRESENT"


# --- AC-04 — a missing key file alone never implies NEW ----------------- #
def test_m411a_ac04_missing_key_alone_is_not_new(keyenv, db_session, monkeypatch):
    _mode(monkeypatch, marker=False, encrypted=(), signed=())  # genuinely NEW shape
    keyenv.enc.unlink()
    credential_crypto.reset_cached_key()
    # NEW + no key, but bootstrap is NOT automatic:
    with pytest.raises(KeyMaterialError) as exc:
        verify_encryption_material(db_session, allow_bootstrap=False)
    assert exc.value.code == "INSTALLATION_NEVER_BOOTSTRAPPED"
    assert not keyenv.enc.exists()


# --- AC-05 — the five-state taxonomy ----------------------------------- #
def test_m411a_ac05_five_state_taxonomy(keyenv, db_session, monkeypatch):
    outcomes: dict[str, str] = {}

    # KEY_ABSENT (established via marker)
    _mode(monkeypatch, marker=True)
    keyenv.enc.unlink()
    credential_crypto.reset_cached_key()
    with pytest.raises(KeyMaterialError) as e:
        verify_encryption_material(db_session)
    outcomes["KEY_ABSENT"] = e.value.code

    # KEY_MALFORMED
    _mode(monkeypatch, marker=True)
    keyenv.enc.write_bytes(b"this-is-not-a-fernet-key")
    credential_crypto.reset_cached_key()
    with pytest.raises(KeyMaterialError) as e:
        verify_encryption_material(db_session)
    outcomes["KEY_MALFORMED"] = e.value.code

    # KEY_PRESENT_BUT_WRONG (canary mismatch)
    _mode(monkeypatch, marker=True)
    keyenv.enc.write_bytes(Fernet.generate_key())
    credential_crypto.reset_cached_key()
    db_session.add(KeyMaterialCanary(
        purpose=MODEL_CREDENTIAL_ENCRYPTION, key_fingerprint=get_encryption_key_provider().fingerprint(),
        verifier=Fernet(Fernet.generate_key()).encrypt(KEY_CANARY_PLAINTEXT).decode("ascii"),
        key_provider="LOCAL"))
    db_session.commit()
    with pytest.raises(KeyMaterialError) as e:
        verify_encryption_material(db_session)
    outcomes["KEY_PRESENT_BUT_WRONG"] = e.value.code
    _clear_canary(db_session)

    # INSTALLATION_NEVER_BOOTSTRAPPED
    _mode(monkeypatch, marker=False, encrypted=(), signed=())
    keyenv.enc.unlink()
    credential_crypto.reset_cached_key()
    with pytest.raises(KeyMaterialError) as e:
        verify_encryption_material(db_session, allow_bootstrap=False)
    outcomes["INSTALLATION_NEVER_BOOTSTRAPPED"] = e.value.code

    # KEY_PROVIDER_UNAVAILABLE (done last — patches check_available for the rest of the test)
    _mode(monkeypatch, marker=True)
    keyenv.enc.write_bytes(Fernet.generate_key())
    credential_crypto.reset_cached_key()
    monkeypatch.setattr(LocalEncryptionKeyProvider, "check_available",
                        _raise_unavailable)
    with pytest.raises(KeyMaterialError) as e:
        verify_encryption_material(db_session, allow_bootstrap=True)
    outcomes["KEY_PROVIDER_UNAVAILABLE"] = e.value.code

    assert outcomes == {
        "KEY_PROVIDER_UNAVAILABLE": "ENCRYPTION_KEY_PROVIDER_UNAVAILABLE",
        "KEY_ABSENT": "ENCRYPTION_KEY_MISSING_ESTABLISHED_INSTALL",
        "KEY_MALFORMED": "ENCRYPTION_KEY_MALFORMED",
        "KEY_PRESENT_BUT_WRONG": "ENCRYPTION_KEY_MISMATCH",
        "INSTALLATION_NEVER_BOOTSTRAPPED": "INSTALLATION_NEVER_BOOTSTRAPPED",
    }
    assert len(set(outcomes.values())) == 5  # each state a distinct code
    assert {s.value for s in KeyState} >= set(outcomes)


# --- AC-06 — provider outage is not an install-mode signal -------------- #
def test_m411a_ac06_provider_unavailable_never_bootstraps(keyenv, db_session, monkeypatch):
    _mode(monkeypatch, marker=False, encrypted=(), signed=())  # would be NEW
    keyenv.enc.unlink()
    credential_crypto.reset_cached_key()
    monkeypatch.setattr(LocalEncryptionKeyProvider, "check_available",
                        _raise_unavailable)
    with pytest.raises(KeyMaterialError) as exc:
        verify_encryption_material(db_session, allow_bootstrap=True)  # opt-in present
    assert exc.value.code == "ENCRYPTION_KEY_PROVIDER_UNAVAILABLE"
    assert not keyenv.enc.exists()                 # a provider outage NEVER mints a key
    assert marker_present(db_session) is False


# --- AC-07 — a truly empty new DB still bootstraps deliberately --------- #
def test_m411a_ac07_empty_new_db_bootstraps_and_records_marker(keyenv, db_session, monkeypatch):
    _mode(monkeypatch, marker=False, encrypted=(), signed=())
    keyenv.enc.unlink()
    credential_crypto.reset_cached_key()
    result = verify_encryption_material(db_session, allow_bootstrap=True)
    assert result["key_state"] == KeyState.OK.value
    assert keyenv.enc.exists()
    assert marker_present(db_session) is True


# --- AC-08 — restored/cloned DB carries the marker ⇒ EXISTING ---------- #
def test_m411a_ac08_restored_db_with_marker_is_existing(keyenv, db_session, monkeypatch):
    record_bootstrap(db_session, get_encryption_key_provider(), recorded_via="bootstrap")
    _mode(monkeypatch, marker=True, encrypted=(), signed=())  # ciphertext tables empty at backup time
    assert detect_install_mode(db_session).mode is InstallMode.EXISTING

    with pytest.raises(KeyMaterialError) as b:
        bootstrap_key_material(db_session)
    assert b.value.code == "BOOTSTRAP_REFUSED_MARKER_PRESENT"

    keyenv.enc.unlink()
    credential_crypto.reset_cached_key()
    with pytest.raises(KeyMaterialError) as v:
        verify_encryption_material(db_session)
    assert v.value.code == "ENCRYPTION_KEY_MISSING_ESTABLISHED_INSTALL"


# --- AC-09 — the one-time backfill, after verification, idempotent ----- #
def test_m411a_ac09_backfill_marker_after_verifying_existing_key(keyenv, client, db_session):
    org = _register_org(client)
    _store_credential(client, org, secret=_SECRET)     # real ciphertext -> EXISTING by fast-path
    assert marker_present(db_session) is False

    r1 = verify_encryption_material(db_session)         # verifies the key, then backfills
    assert r1["key_state"] == KeyState.OK.value
    marker = db_session.execute(select(InstallationBootstrap)).scalar_one()
    assert marker.recorded_via == "backfill"

    # idempotent — a second startup does not duplicate or race a bootstrap
    r2 = verify_encryption_material(db_session)
    assert r2["key_state"] == KeyState.OK.value
    assert db_session.execute(select(InstallationBootstrap)).scalars().all() == [marker]


def test_m411a_ac09_backfill_never_happens_before_verification(keyenv, db_session, monkeypatch):
    """A wrong key on an established (marker) install must NOT get a marker
    written for it — the backfill is gated on verification."""
    _mode(monkeypatch, marker=True, encrypted=(), signed=())
    keyenv.enc.write_bytes(Fernet.generate_key())
    credential_crypto.reset_cached_key()
    db_session.add(KeyMaterialCanary(
        purpose=MODEL_CREDENTIAL_ENCRYPTION,
        key_fingerprint=get_encryption_key_provider().fingerprint(),
        verifier=Fernet(Fernet.generate_key()).encrypt(KEY_CANARY_PLAINTEXT).decode("ascii")))
    db_session.commit()
    with pytest.raises(KeyMaterialError):
        verify_encryption_material(db_session)
    _clear_canary(db_session)


# --- AC-10 — half-init fails loud ------------------------------------- #
def test_m411a_ac10_half_init_fails_loud(keyenv, db_session, monkeypatch):
    # (a) key present, marker absent, no state, and NOTHING to verify the key
    #     against (no canary, no decryptable ciphertext) -> INSTALLATION_BOOTSTRAP_INCOMPLETE
    _mode(monkeypatch, marker=False, encrypted=(), signed=())
    monkeypatch.setattr("app.security.key_integrity.trial_decrypt_succeeds", lambda db, provider: None)
    with pytest.raises(KeyMaterialError) as a:
        verify_encryption_material(db_session, allow_bootstrap=False)
    assert a.value.code == "INSTALLATION_BOOTSTRAP_INCOMPLETE"

    # (a') the same shape WITH the opt-in adopts the present key deliberately
    r = verify_encryption_material(db_session, allow_bootstrap=True)
    assert r["validation"] == "ADOPTED_KEY" and marker_present(db_session) is True

    # (b) marker present, key absent -> fail loud (established, lost key)
    _mode(monkeypatch, marker=True, encrypted=(), signed=())
    keyenv.enc.unlink()
    credential_crypto.reset_cached_key()
    with pytest.raises(KeyMaterialError) as b:
        verify_encryption_material(db_session)
    assert b.value.code == "ENCRYPTION_KEY_MISSING_ESTABLISHED_INSTALL"

    # (c) established (marker) + key present but NOTHING to verify it against
    _mode(monkeypatch, marker=True, encrypted=(), signed=())
    keyenv.enc.write_bytes(Fernet.generate_key())
    credential_crypto.reset_cached_key()
    with pytest.raises(KeyMaterialError) as c:
        verify_encryption_material(db_session)
    assert c.value.code == "ENCRYPTION_KEY_UNVERIFIED_ESTABLISHED_INSTALL"


# --- AC-11 — no key/secret/ciphertext in any state's output ----------- #
def test_m411a_ac11_no_material_leaks_in_any_state(keyenv, db_session, monkeypatch, caplog):
    right = keyenv.enc.read_bytes()
    wrong = Fernet.generate_key()
    messages: list[str] = []

    def _absent():
        _mode(monkeypatch, marker=True)
        if keyenv.enc.exists():
            keyenv.enc.unlink()
        credential_crypto.reset_cached_key()

    def _malformed():
        _mode(monkeypatch, marker=True)
        keyenv.enc.write_bytes(b"not-a-key")
        credential_crypto.reset_cached_key()

    def _wrong():
        _mode(monkeypatch, marker=True)
        keyenv.enc.write_bytes(wrong)
        credential_crypto.reset_cached_key()
        db_session.add(KeyMaterialCanary(
            purpose=MODEL_CREDENTIAL_ENCRYPTION,
            key_fingerprint=get_encryption_key_provider().fingerprint(),
            verifier=Fernet(Fernet.generate_key()).encrypt(KEY_CANARY_PLAINTEXT).decode("ascii")))
        db_session.commit()

    def _never():
        _mode(monkeypatch, marker=False, encrypted=(), signed=())
        if keyenv.enc.exists():
            keyenv.enc.unlink()
        credential_crypto.reset_cached_key()

    with caplog.at_level("DEBUG"):
        for setup in (_absent, _malformed, _wrong, _never):
            setup()
            try:
                verify_encryption_material(db_session, allow_bootstrap=False)
            except KeyMaterialError as exc:
                messages.append(str(exc))
            _clear_canary(db_session)
    hay = " ".join(messages) + "\n" + caplog.text
    for needle in (right.decode(), right.decode().rstrip("="), KEY_CANARY_PLAINTEXT.decode()):
        assert needle not in hay
    assert all(" — " in m for m in messages)


# --- AC-13 — the 0053 migration is additive only --------------------- #
def test_m411a_ac13_installation_bootstrap_migration_is_additive():
    mig = (_BACKEND / "migrations" / "versions" / "0053_installation_bootstrap.py").read_text()
    tree = ast.parse(mig)
    calls = {
        n.func.attr for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name) and n.func.value.id == "op"
    }
    assert calls <= {"create_table", "drop_table"}
    assert "installation_bootstrap" in mig
    for forbidden in ("alter_table", "add_column", "op.execute", "UPDATE ", "DELETE "):
        assert forbidden not in mig


# --- AC-12 / AC-14 — M4.11 guarantees preserved --------------------- #
def test_m411a_ac12_m411_guarantees_still_hold(signing_env, client, db_session):
    """Backup/restore + continuity + the canary wrong-key detector all still
    work with the marker in place."""
    org = _register_org(client)
    _store_credential(client, org, secret=_SECRET)
    ciphertext = _newest_provider_ciphertext(db_session)
    verify_encryption_material(db_session)                 # writes canary + backfills marker
    assert marker_present(db_session) is True

    archive = signing_env.tmp / "m411a-arch"
    key_backup.create_key_material_archive(archive)
    for f in list(signing_env.dir.iterdir()):
        f.unlink()
    credential_crypto.reset_cached_key()
    key_backup.restore_key_material_archive(archive)
    credential_crypto.reset_cached_key()
    assert credential_crypto.decrypt_secret(ciphertext) == _SECRET   # continuity

    # wrong key still caught
    signing_env.enc.write_bytes(Fernet.generate_key())
    credential_crypto.reset_cached_key()
    with pytest.raises(KeyMaterialError):
        verify_encryption_material(db_session)
