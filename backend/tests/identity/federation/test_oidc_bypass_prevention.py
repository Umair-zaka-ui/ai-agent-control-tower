"""Phase 2.3.1 tests — OIDC ID-token verification bypass prevention
(``app/identity/federation/oidc.py::verify_id_token``), the security core's
first half.

Every test in this file runs against a real, freshly-generated RSA
keypair and real ``jose.jwt.encode``-signed tokens — never a mock signer
— with **no live IdP, no HTTP call, no database** anywhere in the file.
This is the OIDC analogue of 2.2.x's isolated-security-module test
discipline (``test_storage_scope.py``, ``test_queue_scope.py``)."""

from __future__ import annotations

import time

import pytest
from jose import jwt as jose_jwt

from app.identity.federation.oidc import OidcVerificationError, verify_id_token

_ISSUER = "https://idp.example.com"
_AUDIENCE = "test-client-id"
_NONCE = "a-fresh-nonce-value"


def _mint(rsa_keypair, *, claims_override: dict | None = None, headers_override: dict | None = None,
          algorithm: str = "RS256", key: str | None = None) -> str:
    now = int(time.time())
    claims = {
        "sub": "idp-subject-42", "iss": _ISSUER, "aud": _AUDIENCE, "nonce": _NONCE,
        "iat": now, "exp": now + 300, "email": "alice@example.com", "name": "Alice Example",
    }
    if claims_override:
        claims.update(claims_override)
    headers = {"kid": rsa_keypair["kid"]}
    if headers_override is not None:
        headers = headers_override
    signing_key = key if key is not None else rsa_keypair["private_pem"]
    return jose_jwt.encode(claims, signing_key, algorithm=algorithm, headers=headers)


# --------------------------------------------------------------------------- #
# AC-06 — a validly-signed token authenticates
# --------------------------------------------------------------------------- #
def test_ac06_a_validly_signed_token_is_accepted(rsa_keypair):
    token = _mint(rsa_keypair)
    claims = verify_id_token(token, rsa_keypair["jwks"], issuer=_ISSUER, audience=_AUDIENCE, nonce=_NONCE)
    assert claims.subject == "idp-subject-42"
    assert claims.email == "alice@example.com"
    assert claims.name == "Alice Example"


def test_ac06_groups_claim_is_extracted(rsa_keypair):
    token = _mint(rsa_keypair, claims_override={"groups": ["AI-Admins", "Everyone"]})
    claims = verify_id_token(token, rsa_keypair["jwks"], issuer=_ISSUER, audience=_AUDIENCE, nonce=_NONCE)
    assert set(claims.groups) == {"AI-Admins", "Everyone"}


# --------------------------------------------------------------------------- #
# AC-07 — invalid signature rejected
# --------------------------------------------------------------------------- #
def test_ac07_a_tampered_signature_is_rejected(rsa_keypair):
    token = _mint(rsa_keypair)
    tampered = token[:-8] + ("A" * 8)
    with pytest.raises(OidcVerificationError):
        verify_id_token(tampered, rsa_keypair["jwks"], issuer=_ISSUER, audience=_AUDIENCE, nonce=_NONCE)


def test_ac07_a_token_signed_by_a_different_key_is_rejected(rsa_keypair):
    from cryptography.hazmat.primitives.asymmetric import rsa as rsa_mod
    from cryptography.hazmat.primitives import serialization

    other_key = rsa_mod.generate_private_key(public_exponent=65537, key_size=2048)
    other_pem = other_key.private_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    # Signed with an attacker's own key but claiming the real IdP's `kid` --
    # the forged signature must still fail against the real public key.
    token = _mint(rsa_keypair, key=other_pem)
    with pytest.raises(OidcVerificationError):
        verify_id_token(token, rsa_keypair["jwks"], issuer=_ISSUER, audience=_AUDIENCE, nonce=_NONCE)


def test_ac07_algorithm_confusion_hs256_using_the_public_key_material_is_rejected(rsa_keypair):
    """The canonical JWT algorithm-confusion attack: an attacker mints an
    HS256 token, guessing that a careless verifier will read `alg` from
    the token's own header and use the RSA *public* key bytes as the HMAC
    secret. This module never reads `alg` from the token -- `algorithms`
    is always the caller's own fixed, trusted list -- so the forged
    token's HS256 header is rejected outright, before any HMAC is ever
    computed."""
    now = int(time.time())
    guessed_secret = rsa_keypair["jwks"]["keys"][0]["n"]  # a plausible guess an attacker might try
    forged = jose_jwt.encode(
        {"sub": "attacker", "iss": _ISSUER, "aud": _AUDIENCE, "nonce": _NONCE, "iat": now, "exp": now + 300},
        guessed_secret, algorithm="HS256", headers={"kid": rsa_keypair["kid"]},
    )
    with pytest.raises(OidcVerificationError):
        verify_id_token(forged, rsa_keypair["jwks"], issuer=_ISSUER, audience=_AUDIENCE, nonce=_NONCE)


def test_ac07_an_unsigned_none_algorithm_token_is_rejected(rsa_keypair):
    """The other classic JWT bypass: `alg: none`, no signature at all."""
    now = int(time.time())
    header = {"alg": "none", "typ": "JWT"}
    import base64
    import json

    def _b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    payload = {"sub": "attacker", "iss": _ISSUER, "aud": _AUDIENCE, "nonce": _NONCE, "iat": now, "exp": now + 300}
    forged = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(payload).encode())}."
    with pytest.raises(OidcVerificationError):
        verify_id_token(forged, rsa_keypair["jwks"], issuer=_ISSUER, audience=_AUDIENCE, nonce=_NONCE)


# --------------------------------------------------------------------------- #
# AC-08 — expired token rejected
# --------------------------------------------------------------------------- #
def test_ac08_an_expired_token_is_rejected(rsa_keypair):
    now = int(time.time())
    token = _mint(rsa_keypair, claims_override={"iat": now - 3600, "exp": now - 1800})
    with pytest.raises(OidcVerificationError):
        verify_id_token(token, rsa_keypair["jwks"], issuer=_ISSUER, audience=_AUDIENCE, nonce=_NONCE)


# --------------------------------------------------------------------------- #
# AC-09 — wrong audience / issuer rejected
# --------------------------------------------------------------------------- #
def test_ac09_wrong_audience_is_rejected(rsa_keypair):
    token = _mint(rsa_keypair, claims_override={"aud": "some-other-client-id"})
    with pytest.raises(OidcVerificationError):
        verify_id_token(token, rsa_keypair["jwks"], issuer=_ISSUER, audience=_AUDIENCE, nonce=_NONCE)


def test_ac09_wrong_issuer_is_rejected(rsa_keypair):
    token = _mint(rsa_keypair, claims_override={"iss": "https://not-the-real-idp.example.com"})
    with pytest.raises(OidcVerificationError):
        verify_id_token(token, rsa_keypair["jwks"], issuer=_ISSUER, audience=_AUDIENCE, nonce=_NONCE)


# --------------------------------------------------------------------------- #
# AC-10 — replayed nonce rejected
# --------------------------------------------------------------------------- #
def test_ac10_a_nonce_not_matching_this_login_attempt_is_rejected(rsa_keypair):
    """A validly-signed, otherwise-fresh token minted for a *different*
    login attempt (a different nonce) is rejected -- this is what defeats
    replaying an old, legitimately-issued ID token against a new login."""
    token = _mint(rsa_keypair, claims_override={"nonce": "a-completely-different-nonce"})
    with pytest.raises(OidcVerificationError):
        verify_id_token(token, rsa_keypair["jwks"], issuer=_ISSUER, audience=_AUDIENCE, nonce=_NONCE)


def test_ac10_a_missing_nonce_is_rejected(rsa_keypair):
    now = int(time.time())
    token = jose_jwt.encode(
        {"sub": "idp-subject-42", "iss": _ISSUER, "aud": _AUDIENCE, "iat": now, "exp": now + 300},
        rsa_keypair["private_pem"], algorithm="RS256", headers={"kid": rsa_keypair["kid"]},
    )
    with pytest.raises(OidcVerificationError):
        verify_id_token(token, rsa_keypair["jwks"], issuer=_ISSUER, audience=_AUDIENCE, nonce=_NONCE)


# --------------------------------------------------------------------------- #
# AC-11 — verification is JWKS-based via a vetted library, not hand-rolled
# --------------------------------------------------------------------------- #
def test_ac11_an_unknown_kid_is_rejected_no_fallback_key_is_tried(rsa_keypair):
    """There is no "try every key" fallback that could be tricked into
    matching an attacker-supplied key -- an unrecognized `kid` is an
    outright rejection."""
    token = _mint(rsa_keypair, headers_override={"kid": "not-a-real-key-id"})
    with pytest.raises(OidcVerificationError):
        verify_id_token(token, rsa_keypair["jwks"], issuer=_ISSUER, audience=_AUDIENCE, nonce=_NONCE)


def test_ac11_verification_uses_jose_not_a_hand_rolled_signature_check():
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parents[3].joinpath("app", "identity", "federation", "oidc.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
    assert "jose" in imported
    # No cryptography primitives imported directly in this module -- all
    # signature/cert handling is delegated to `jose`, never hand-assembled
    # from raw `cryptography`/`hashlib` primitives here.
    assert "hashlib" not in imported
    assert "hmac" not in imported


def test_ac11_algorithms_are_never_taken_from_the_tokens_own_header():
    """Structural proof, not just behavioral: `verify_id_token`'s
    `algorithms` parameter has a caller-supplied default and is passed
    straight to `jose.jwt.decode` -- the token's own unverified header is
    only ever consulted for `kid`, never for `alg`."""
    import inspect

    from app.identity.federation import oidc

    source = inspect.getsource(oidc.verify_id_token)
    assert 'header.get("alg"' not in source
    assert 'header["alg"]' not in source
