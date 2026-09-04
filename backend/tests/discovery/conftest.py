"""Fixtures for the Phase 5.2 (M5.2) Agent Discovery Framework tests.

Mirrors ``tests/integration/conftest.py`` exactly — a new top-level domain
gets its own test directory and its own minimal ``client``/``admin``/
``db_session`` fixtures, the established convention for every prior domain
in this codebase."""

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


def _register_org(client: TestClient, org_name: str) -> dict:
    email = f"disc_{uuid.uuid4().hex[:10]}@example.com"
    reg = client.post(
        "/auth/register",
        json={"organization_name": org_name, "name": "Owner", "email": email, "password": PASSWORD},
    )
    assert reg.status_code == 201, reg.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"],
            "email": email}


@pytest.fixture()
def admin(client: TestClient) -> dict:
    return _register_org(client, "Discovery Org")


@pytest.fixture()
def other_org_admin(client: TestClient) -> dict:
    return _register_org(client, "Other Discovery Org")


@pytest.fixture()
def viewer(client: TestClient, admin: dict) -> dict:
    """A VIEWER-role member of ``admin``'s org — VIEWER has none of the new
    ``discovery.source.*`` permissions, so this exercises "authenticated but
    not permitted" (403)."""
    email = f"discv_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": email, "display_name": "Viewer", "password": PASSWORD, "role": "VIEWER",
        "organization_id": admin["organization_id"],
    })
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    return {"headers": {"Authorization": f"Bearer {tokens['access_token']}"}}
