"""Recovery dashboard, rate limiting, and dead-code guards (4.2.2.3.3 §15, §18, §24, §25)."""

from __future__ import annotations

import pathlib
import re
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.identity.auth.enums import AuthEventType
from app.identity.errors import ErrorCode
from app.main import app

PASSWORD = "T3st!Passw0rd#Ok"

_APP = pathlib.Path(__file__).resolve().parents[3] / "app"
_SOURCES = "\n".join(
    p.read_text(encoding="utf-8")
    for p in _APP.rglob("*.py")
    if p.name not in ("enums.py", "errors.py")
)

_RECOVERY_EVENTS = [
    AuthEventType.PASSWORD_RESET_REQUESTED,
    AuthEventType.PASSWORD_RESET_COMPLETED,
    AuthEventType.PASSWORD_RESET_FAILED,
    AuthEventType.EMAIL_CHANGE_REQUESTED,
    AuthEventType.EMAIL_CHANGED,
    AuthEventType.EMAIL_CHANGE_VERIFIED,
    AuthEventType.RECOVERY_REQUEST_EXPIRED,
    AuthEventType.RECOVERY_REQUEST_REVOKED,
]

_RECOVERY_CODES = [
    ErrorCode.RESET_TOKEN_INVALID,
    ErrorCode.RESET_TOKEN_EXPIRED,
    ErrorCode.RESET_TOKEN_USED,
    ErrorCode.EMAIL_VERIFICATION_EXPIRED,
    ErrorCode.PASSWORD_RESET_DISABLED,
    ErrorCode.INVALID_RECOVERY_REQUEST,
    ErrorCode.EMAIL_ALREADY_IN_USE,
]


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _register_and_login(client: TestClient) -> tuple[str, dict]:
    email = f"rec_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post(
        "/auth/register",
        json={"organization_name": "Rec Org", "name": "Owner", "email": email, "password": PASSWORD},
    ).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    return email, tokens


def test_every_recovery_event_is_emitted() -> None:
    dead = [e.name for e in _RECOVERY_EVENTS if not re.search(rf"AuthEventType\.{e.name}\b", _SOURCES)]
    assert not dead, f"recovery events defined but never emitted: {dead}"


def test_every_recovery_error_code_is_raised() -> None:
    dead = [c for c in _RECOVERY_CODES if not re.search(rf"ErrorCode\.{c}\b", _SOURCES)]
    assert not dead, f"recovery error codes defined but never raised: {dead}"


def test_recovery_events_dashboard_lists_reset_activity(client: TestClient) -> None:
    email, tokens = _register_and_login(client)
    # Generate a reset request so there is something to see.
    client.post("/api/v1/auth/forgot-password", json={"email": email})

    resp = client.get(
        "/api/v1/security/recovery-events",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert resp.status_code == 200
    types = {row["event_type"] for row in resp.json()}
    assert "PASSWORD_RESET_REQUESTED" in types


def test_recovery_events_requires_permission(client: TestClient) -> None:
    assert client.get("/api/v1/security/recovery-events").status_code in (401, 403)


def test_forgot_password_is_rate_limited(client: TestClient, monkeypatch) -> None:
    """§15: 5 requests/min/IP by default. The 6th within the window is throttled."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_DEFAULT_REQUESTS", 5)
    email = f"rl_{uuid.uuid4().hex[:8]}@example.com"
    codes = [
        client.post("/api/v1/auth/forgot-password", json={"email": email}).status_code
        for _ in range(7)
    ]
    assert codes.count(429) >= 1, codes
