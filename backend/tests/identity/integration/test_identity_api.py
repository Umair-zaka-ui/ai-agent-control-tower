"""Identity API integration tests (versioning, RBAC, error envelope)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

BASE = "/api/v1/identity"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _register(client: TestClient) -> tuple[str, uuid.UUID]:
    email = f"owner_{uuid.uuid4().hex[:10]}@example.com"
    token = client.post(
        "/auth/register",
        json={"organization_name": "Identity API Org", "name": "Owner", "email": email, "password": "password123"},
    ).json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    return token, uuid.UUID(me["organization_id"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_versioned_user_endpoints(client: TestClient) -> None:
    token, org_id = _register(client)
    admin = _auth(token)

    # Create a user under the versioned identity API.
    email = f"member_{uuid.uuid4().hex[:8]}@example.com"
    r = client.post(
        f"{BASE}/users",
        headers=admin,
        json={
            "email": email,
            "display_name": "New Member",
            "password": "Str0ngPass",
            "organization_id": str(org_id),
            "role": "VIEWER",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == email and body["display_name"] == "New Member"
    user_id = body["id"]

    # List + get.
    listed = client.get(f"{BASE}/users", headers=admin).json()
    assert any(u["id"] == user_id for u in listed)
    assert client.get(f"{BASE}/users/{user_id}", headers=admin).json()["id"] == user_id

    # Lifecycle: suspend then activate.
    assert client.post(f"{BASE}/users/{user_id}/suspend", headers=admin).json()["is_active"] is False
    assert client.post(f"{BASE}/users/{user_id}/activate", headers=admin).json()["is_active"] is True


def test_error_envelope_and_request_id(client: TestClient) -> None:
    token, _ = _register(client)
    admin = _auth(token)
    missing = uuid.uuid4()
    r = client.get(f"{BASE}/users/{missing}", headers={**admin, "x-request-id": "req-123"})
    assert r.status_code == 404
    body = r.json()
    # Standard envelope (SRS §18): success/error{code,message}/request_id.
    assert body["success"] is False
    assert body["error"]["code"] == "USER_NOT_FOUND"
    assert "message" in body["error"]
    assert body["request_id"] == "req-123"


def test_organizations_departments_roles(client: TestClient) -> None:
    token, org_id = _register(client)
    admin = _auth(token)

    orgs = client.get(f"{BASE}/organizations", headers=admin).json()
    assert len(orgs) == 1 and orgs[0]["id"] == str(org_id)

    dept = client.post(
        f"{BASE}/departments",
        headers=admin,
        json={"organization_id": str(org_id), "name": "Compliance"},
    )
    assert dept.status_code == 201, dept.text
    assert any(d["name"] == "Compliance" for d in client.get(f"{BASE}/departments", headers=admin).json())

    roles = client.get(f"{BASE}/roles", headers=admin).json()
    assert any(r["name"] == "SUPER_ADMIN" for r in roles)


def test_rbac_viewer_cannot_create_users(client: TestClient) -> None:
    token, org_id = _register(client)
    admin = _auth(token)
    # A VIEWER lacks user.create.
    viewer_email = f"viewer_{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/users",
        headers=admin,
        json={"name": "Vic", "email": viewer_email, "password": "password123", "role": "VIEWER"},
    )
    vtoken = client.post("/auth/login", json={"email": viewer_email, "password": "password123"}).json()["access_token"]
    r = client.post(
        f"{BASE}/users",
        headers=_auth(vtoken),
        json={
            "email": f"x_{uuid.uuid4().hex[:8]}@example.com",
            "display_name": "X",
            "password": "Str0ngPass",
            "organization_id": str(org_id),
        },
    )
    assert r.status_code == 403


def test_unauthenticated_is_rejected(client: TestClient) -> None:
    # The platform's bearer scheme rejects missing credentials with 403.
    assert client.get(f"{BASE}/users").status_code in (401, 403)
