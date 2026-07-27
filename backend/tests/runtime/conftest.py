"""Fixtures for the ``tests/runtime/`` suite (Phase 5.2.6 compatibility
detection, Phase 5.2.4 signing/provenance/attestation, Phase 5.7a.2
provider fixture replay)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.authorization.seeding import seed_authorization
from app.core.database import SessionLocal
from app.main import app

PASSWORD = "T3st!Passw0rd#Ok"

# --------------------------------------------------------------------------- #
# Phase 5.7a.2 — provider fixture replay. ``OpenAICompatibleProvider`` has no
# awareness of any of this: it always calls whatever ``httpx.BaseTransport``
# its constructor was given (or built by its own ``_build_default_transport``
# if none was), and this file is the only place that ever substitutes one.
# --------------------------------------------------------------------------- #
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "providers"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


def replay_transport(name: str, *, status_code: int = 200) -> httpx.MockTransport:
    """An ``httpx`` transport that returns the named fixture's recorded
    response regardless of what request is sent — a request never leaves
    the process. See ``fixtures/providers/README.md`` for how the fixtures
    themselves were produced."""
    body = load_fixture(name)

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=body, request=request)

    return httpx.MockTransport(_handler)


@pytest.fixture(autouse=True)
def _default_openai_compatible_transport(monkeypatch) -> None:
    """The provider conformance suite (``test_provider_abstraction.py``)
    constructs every entry in ``PROVIDERS_UNDER_TEST`` with zero
    arguments, including ``OpenAICompatibleProvider`` once appended
    (Phase 5.7a.2) — there is no real endpoint to call in that context. This
    globally substitutes the *default* transport (used only when a test
    doesn't inject its own via the ``transport=`` constructor kwarg) with a
    replay of ``simple_completion.json``, so the zero-arg conformance path
    gets a real, valid ``ModelResponse`` instead of trying to open a real
    socket. Tests that need a *specific* fixture still pass ``transport=
    replay_transport(...)`` explicitly, which always wins over this
    default."""
    from app.runtime.providers.openai_compatible import OpenAICompatibleProvider

    monkeypatch.setattr(
        OpenAICompatibleProvider, "_build_default_transport",
        lambda self: replay_transport("simple_completion.json"),
    )


@pytest.fixture(scope="session", autouse=True)
def _seed_authorization_once() -> None:
    db = SessionLocal()
    try:
        seed_authorization(db)
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _isolated_signing_key(monkeypatch) -> None:
    """Phase 5.2.4 — ``signing_keys`` has no organization scoping (matching
    the SRS's own table definition, and Part 1's precedent of global, not
    per-org, catalogs — e.g. release channels). That means rotating or
    revoking "the" default key is process-wide, not scoped to one test's
    org: without this fixture, one test revoking the shared key would
    silently break every other test's ability to publish/sign — in this
    same run, *and in every future run against the same database*, since
    the revocation is a committed row, not something any per-test
    transaction rolls back. Every test in this directory gets its own
    private key_id instead, so no test can corrupt another's (or a future
    run's) state."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "SIGNING_DEFAULT_KEY_ID", f"test-{uuid.uuid4().hex[:12]}")


@pytest.fixture()
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def admin(client: TestClient) -> dict:
    """Register a fresh org (owner = SUPER_ADMIN) and return auth headers + ids."""
    email = f"compat_{uuid.uuid4().hex[:10]}@example.com"
    reg = client.post(
        "/auth/register",
        json={"organization_name": "Compat Org", "name": "Owner", "email": email, "password": PASSWORD},
    )
    assert reg.status_code == 201, reg.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    ).json()
    return {
        "headers": {"Authorization": f"Bearer {tokens['access_token']}"},
        "user_id": me["user"]["id"],
        "organization_id": me["user"]["organization_id"],
        "email": email,
    }
