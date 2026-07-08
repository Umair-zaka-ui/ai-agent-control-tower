"""The `/api/v1/auth` access token must work across the whole platform.

The SPA signs in at ``/api/v1/auth/login`` and then calls the *legacy* endpoints
(`/dashboard`, `/agents`, `/policies`, `/approvals`, `/audit`) with that token.
Those endpoints authenticate via ``app.api.deps.get_current_user`` →
``decode_access_token``.

Until this was fixed, ``decode_access_token`` rejected the new token outright (it
carries ``aud``/``iss`` claims the legacy decoder did not expect), so *every*
dashboard request 401'd for real users. No test crossed that boundary, and the
frontend typechecks and builds regardless — the failure only appears at runtime.

The second half of this file pins the security consequence: once the legacy path
accepts a session-bearing token, it must also honour the session. Otherwise
revocation would be "immediate" on `/api/v1/auth/*` and meaningless everywhere else.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.identity.models.session import UserSession
from app.main import app

PASSWORD = "T3st!Passw0rd#Ok"

# Legacy endpoints the dashboard actually calls on every page load.
LEGACY_ENDPOINTS = ["/dashboard/summary", "/agents", "/policies", "/approvals", "/rbac/me"]


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _register(client: TestClient) -> tuple[str, str]:
    email = f"interop_{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        "/auth/register",
        json={"organization_name": "Interop Org", "name": "Owner", "email": email,
              "password": PASSWORD},
    )
    assert resp.status_code == 201
    return email, resp.json()["access_token"]


def _spa_login(client: TestClient, email: str) -> dict:
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200
    return resp.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# Interop: the SPA's token must authenticate the whole platform
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("endpoint", LEGACY_ENDPOINTS)
def test_spa_token_authenticates_legacy_endpoints(client: TestClient, endpoint: str) -> None:
    email, _ = _register(client)
    tokens = _spa_login(client, email)
    resp = client.get(endpoint, headers=_auth(tokens["access_token"]))
    assert resp.status_code != 401, f"SPA token rejected by {endpoint}: the dashboard is broken"
    assert resp.status_code < 500


def test_legacy_token_still_authenticates_legacy_endpoints(client: TestClient) -> None:
    """The fix must not break the surface it is bolted onto."""
    _, legacy_token = _register(client)
    for endpoint in LEGACY_ENDPOINTS:
        resp = client.get(endpoint, headers=_auth(legacy_token))
        assert resp.status_code != 401, f"legacy token rejected by {endpoint}"


def test_spa_token_authenticates_the_identity_admin_api(client: TestClient) -> None:
    """§32: an administrator uses the dashboard, which holds an /api/v1/auth token."""
    email, _ = _register(client)
    tokens = _spa_login(client, email)
    me = client.get("/api/v1/auth/me", headers=_auth(tokens["access_token"])).json()
    resp = client.get(
        f"/api/v1/identity/sessions?user_id={me['user']['id']}",
        headers=_auth(tokens["access_token"]),
    )
    assert resp.status_code == 200, "admin session UI cannot call the identity API"


# --------------------------------------------------------------------------- #
# Security: accepting the token means honouring its session
# --------------------------------------------------------------------------- #
def test_revoked_session_is_rejected_by_legacy_endpoints_too(client: TestClient) -> None:
    """Revocation must be immediate *platform-wide*, not only on /api/v1/auth.

    Making the legacy decoder accept a session-bearing token without checking the
    session would have created a hole far worse than the one it closed: logout would
    appear to work while every business endpoint kept serving the revoked token.
    """
    email, _ = _register(client)
    tokens = _spa_login(client, email)
    token = tokens["access_token"]

    assert client.get("/dashboard/summary", headers=_auth(token)).status_code == 200

    assert client.post("/api/v1/auth/logout", headers=_auth(token)).status_code == 200

    for endpoint in LEGACY_ENDPOINTS:
        resp = client.get(endpoint, headers=_auth(token))
        assert resp.status_code == 401, f"{endpoint} served a revoked session"


def test_expired_session_is_rejected_by_legacy_endpoints(client: TestClient) -> None:
    email, _ = _register(client)
    tokens = _spa_login(client, email)

    db = SessionLocal()
    try:
        session = db.get(UserSession, uuid.UUID(tokens["session_id"]))
        session.absolute_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    resp = client.get("/dashboard/summary", headers=_auth(tokens["access_token"]))
    assert resp.status_code == 401, "legacy endpoint served a timed-out session"


def test_mfa_challenge_token_cannot_authenticate_legacy_endpoints(
    client: TestClient, monkeypatch
) -> None:
    """An MFA-pending challenge proves only the primary factor. It must never satisfy
    a protected route — on either surface."""
    from app.identity.auth.authentication_service import AuthenticationService

    monkeypatch.setattr(AuthenticationService, "_mfa_required", lambda self, user: True)
    email, _ = _register(client)
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    challenge = resp.json()["mfa_challenge_token"]
    assert challenge

    for endpoint in LEGACY_ENDPOINTS:
        got = client.get(endpoint, headers=_auth(challenge))
        assert got.status_code == 401, f"{endpoint} accepted an MFA challenge token"


def test_refresh_token_is_not_a_bearer_token(client: TestClient) -> None:
    email, _ = _register(client)
    tokens = _spa_login(client, email)
    resp = client.get("/dashboard/summary", headers=_auth(tokens["refresh_token"]))
    assert resp.status_code == 401
