"""Shared fixtures for the federation test suite (Phase 2.3.1).

No shared ``admin``/``client``/``db_session`` fixtures are defined here —
mirroring every other identity test directory (``tests/identity/*``), each
test builds its own ``TestClient(app)``/``SessionLocal()`` directly (see
``REPO_STATE.md`` §7's own note that this domain has no per-directory
conftest). This file only holds the OIDC/SAML cryptographic fixtures the
bypass-prevention tests need — real key material, never a mock signer,
since the whole point of these tests is proving real signature
verification actually runs."""

from __future__ import annotations

import base64
import uuid

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization


def _b64url_uint(n: int) -> str:
    length = (n.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode("ascii")


@pytest.fixture()
def rsa_keypair():
    """A fresh, real RSA keypair + its JWKS representation — never reused
    across tests, so a signature-verification bug can't hide behind key
    reuse."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    numbers = key.public_key().public_numbers()
    kid = f"test-key-{uuid.uuid4().hex[:8]}"
    jwks = {"keys": [{
        "kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid,
        "n": _b64url_uint(numbers.n), "e": _b64url_uint(numbers.e),
    }]}
    return {"private_pem": private_pem, "jwks": jwks, "kid": kid}
