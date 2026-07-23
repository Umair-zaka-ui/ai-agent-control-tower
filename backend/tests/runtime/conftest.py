"""Fixtures for the ``tests/runtime/`` suite (Phase 5.2.6 compatibility
detection, Phase 5.2.4 signing/provenance/attestation)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.authorization.seeding import seed_authorization
from app.core.database import SessionLocal
from app.main import app

PASSWORD = "T3st!Passw0rd#Ok"


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
