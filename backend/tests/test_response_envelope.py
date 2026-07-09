"""Standard response envelope (SRS §5) — success and error parity.

The envelope is off for the rest of the suite (see conftest); here it is turned back
on so the wire contract is asserted directly, mirroring how the rate-limit tests
re-enable rate limiting.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

PASSWORD = "T3st!Passw0rd#Ok"


@pytest.fixture(autouse=True)
def _envelope_on(monkeypatch):
    monkeypatch.setattr(settings, "RESPONSE_ENVELOPE_ENABLED", True)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _login(client: TestClient) -> dict:
    """Register + log in, returning auth headers. Exercises the envelope on the way:
    the login body is itself wrapped, so its tokens live under ``data``."""
    email = f"env_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post(
        "/auth/register",
        json={"organization_name": "Env Org", "name": "Owner", "email": email, "password": PASSWORD},
    ).status_code == 201
    body = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    assert body["success"] is True  # login response is enveloped
    return {"Authorization": f"Bearer {body['data']['access_token']}"}


def test_success_response_is_enveloped(client: TestClient) -> None:
    resp = client.get("/api/v1/auth/me", headers=_login(client))
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert isinstance(body["data"], dict)
    # The real payload is under data, not at the top level.
    assert "user" in body["data"] and "permissions" in body["data"]
    assert body["meta"]["request_id"]
    assert body["meta"]["timestamp"]


def test_error_response_carries_same_envelope_meta(client: TestClient) -> None:
    resp = client.get("/api/v1/auth/me")  # 401, no token
    assert resp.status_code == 401
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"]
    assert body["meta"]["request_id"] == body["request_id"]
    assert body["meta"]["timestamp"]


def test_supplied_request_id_flows_into_success_meta(client: TestClient) -> None:
    resp = client.get(
        "/api/v1/auth/me",
        headers={**_login(client), settings.REQUEST_ID_HEADER: "trace-env-42"},
    )
    assert resp.status_code == 200
    assert resp.json()["meta"]["request_id"] == "trace-env-42"
    assert resp.headers.get(settings.REQUEST_ID_HEADER) == "trace-env-42"


def test_non_api_paths_are_not_enveloped(client: TestClient) -> None:
    # /health is a liveness probe, deliberately outside the API envelope.
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_openapi_schema_is_not_enveloped(client: TestClient) -> None:
    # Wrapping /openapi.json would break Swagger; it lives outside /api.
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    assert "openapi" in resp.json()


def test_security_headers_still_present_on_enveloped_response(client: TestClient) -> None:
    # The rebuilt (enveloped) response must still carry the security + correlation
    # headers applied by the outer middleware.
    resp = client.get("/api/v1/auth/me", headers=_login(client))
    assert resp.status_code == 200
    assert resp.json()["success"] is True  # confirm we hit the enveloped path
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get(settings.REQUEST_ID_HEADER)
