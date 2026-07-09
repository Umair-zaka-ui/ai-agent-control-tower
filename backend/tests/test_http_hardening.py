"""HTTP hardening: request correlation + security headers (Phase 4.2.2.3.5 §15, §16, §23).

These are cross-cutting guarantees that must hold on *every* response — success,
error, and routes outside the identity package — so they are exercised against the
health probe (no auth, no DB) and against an identity error response.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": settings.SECURITY_REFERRER_POLICY,
    "Content-Security-Policy": settings.SECURITY_CSP,
    "Permissions-Policy": settings.SECURITY_PERMISSIONS_POLICY,
}


def test_security_headers_present_on_success(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    for name, value in _SECURITY_HEADERS.items():
        assert resp.headers.get(name) == value, name


def test_security_headers_present_on_error_response(client: TestClient) -> None:
    # An unauthenticated identity route returns the error envelope; the headers must
    # still be attached because the middleware wraps the response, not the handler.
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    for name, value in _SECURITY_HEADERS.items():
        assert resp.headers.get(name) == value, name


def test_request_id_is_generated_when_absent(client: TestClient) -> None:
    resp = client.get("/health")
    rid = resp.headers.get(settings.REQUEST_ID_HEADER)
    assert rid
    # A generated id is a UUID4 string of non-trivial length.
    assert len(rid) >= 8


def test_request_id_is_echoed_when_supplied(client: TestClient) -> None:
    supplied = "trace-abc-123"
    resp = client.get("/health", headers={settings.REQUEST_ID_HEADER: supplied})
    assert resp.headers.get(settings.REQUEST_ID_HEADER) == supplied


def test_request_id_flows_into_the_error_envelope(client: TestClient) -> None:
    supplied = "trace-err-999"
    resp = client.get("/api/v1/auth/me", headers={settings.REQUEST_ID_HEADER: supplied})
    assert resp.status_code == 401
    body = resp.json()
    # SRS §5 error envelope carries the correlation id so a caller can quote it.
    assert body["success"] is False
    assert body["request_id"] == supplied
    assert resp.headers.get(settings.REQUEST_ID_HEADER) == supplied
