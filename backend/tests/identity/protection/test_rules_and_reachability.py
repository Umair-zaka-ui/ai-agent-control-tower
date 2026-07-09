"""Protection rules CRUD + evaluation, and dead-code guards (§16, §27, §31, §32)."""

from __future__ import annotations

import pathlib
import re
import uuid

import pytest
from fastapi.testclient import TestClient

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

_PROTECTION_EVENTS = [
    AuthEventType.ACCOUNT_LOCKED,
    AuthEventType.ACCOUNT_UNLOCKED,
    AuthEventType.BRUTE_FORCE_DETECTED,
    AuthEventType.CREDENTIAL_STUFFING_DETECTED,
    AuthEventType.RISK_LOGIN_DETECTED,
    AuthEventType.LOGIN_CHALLENGE_REQUIRED,
    AuthEventType.IP_BLOCKED,
    AuthEventType.IP_UNBLOCKED,
    AuthEventType.PROTECTION_RULE_CREATED,
    AuthEventType.PROTECTION_RULE_UPDATED,
    AuthEventType.PROTECTION_RULE_DELETED,
    AuthEventType.PROTECTION_RULE_TRIGGERED,
    AuthEventType.CAPTCHA_REQUIRED,
    AuthEventType.SECURITY_REVIEW_REQUIRED,
]

_PROTECTION_CODES = [
    ErrorCode.LOGIN_BLOCKED,
    ErrorCode.RISK_CHALLENGE_REQUIRED,
    ErrorCode.IP_BLOCKED,
    ErrorCode.SECURITY_REVIEW_REQUIRED,
    ErrorCode.ACCOUNT_LOCK_NOT_FOUND,
    ErrorCode.PROTECTION_RULE_NOT_FOUND,
    ErrorCode.BLOCKED_IP_NOT_FOUND,
]


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _register(client: TestClient) -> dict:
    email = f"rule_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post(
        "/auth/register",
        json={"organization_name": "Rule Org", "name": "Owner", "email": email, "password": PASSWORD},
    ).status_code == 201
    return client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()


def _auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_every_protection_event_is_emitted() -> None:
    dead = [e.name for e in _PROTECTION_EVENTS if not re.search(rf"AuthEventType\.{e.name}\b", _SOURCES)]
    assert not dead, f"protection events defined but never emitted: {dead}"


def test_every_protection_error_code_is_raised() -> None:
    dead = [c for c in _PROTECTION_CODES if not re.search(rf"ErrorCode\.{c}\b", _SOURCES)]
    assert not dead, f"protection error codes defined but never raised: {dead}"


def test_protection_rule_crud(client: TestClient) -> None:
    tokens = _register(client)
    created = client.post(
        "/api/v1/security/identity-protection-rules",
        headers=_auth(tokens),
        json={
            "name": "Block severe",
            "conditions": [{"field": "risk_score", "op": "gte", "value": 90}],
            "decision": "BLOCK_IP",
            "priority": 200,
        },
    )
    assert created.status_code == 201, created.text
    rule_id = created.json()["id"]

    listed = client.get("/api/v1/security/identity-protection-rules", headers=_auth(tokens))
    assert any(r["id"] == rule_id for r in listed.json())

    updated = client.put(
        f"/api/v1/security/identity-protection-rules/{rule_id}",
        headers=_auth(tokens), json={"enabled": False},
    )
    assert updated.status_code == 200 and updated.json()["enabled"] is False

    assert client.delete(
        f"/api/v1/security/identity-protection-rules/{rule_id}", headers=_auth(tokens)
    ).status_code == 204


def test_protection_rule_rejects_invalid_decision(client: TestClient) -> None:
    tokens = _register(client)
    resp = client.post(
        "/api/v1/security/identity-protection-rules",
        headers=_auth(tokens),
        json={"name": "bad", "conditions": [], "decision": "NONSENSE"},
    )
    assert resp.status_code == 422


def test_rule_forces_challenge_on_new_device(client: TestClient) -> None:
    """A rule ``new_device is_true → CHALLENGE`` makes a returning login from a new
    device (which has a baseline) require a challenge (§16)."""
    import uuid as _uuid
    from app.core.database import SessionLocal
    from app.identity.protection.detection import LoginSignals
    from app.identity.protection.policy import IdentityProtectionRuleService
    from app.identity.protection.enums import AuthDecision, RiskLevel
    from sqlalchemy import select
    from app.models.user import User

    tokens = _register(client)
    me = client.get("/api/v1/auth/me", headers=_auth(tokens)).json()
    org_id = _uuid.UUID(me["user"]["organization_id"])

    db = SessionLocal()
    try:
        svc = IdentityProtectionRuleService(db)
        svc.create(
            org_id, name="Challenge new devices",
            conditions=[{"field": "new_device", "op": "is_true"}],
            decision=AuthDecision.CHALLENGE.value,
        )
        db.commit()
        signals = LoginSignals()
        signals.flags["new_device"] = True
        match = svc.evaluate(org_id, risk_score=20, risk_level=RiskLevel.LOW, signals=signals)
        assert match is not None and match[0] is AuthDecision.CHALLENGE
    finally:
        db.close()
