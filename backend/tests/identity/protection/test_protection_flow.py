"""Account-protection integration: lockout, progressive, brute-force, admin console (§35)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.identity.auth.enums import AuthEventType
from app.identity.protection.enums import AccountLockStatus
from app.identity.models.protection import AccountLock, IdentityRiskEvent
from app.identity.models.security_event import SecurityEvent
from app.main import app
from app.models.user import User

PASSWORD = "T3st!Passw0rd#Ok"
NEW_PASSWORD = "Rt7&kLm2!Qw9zP"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _register(client: TestClient) -> tuple[str, dict]:
    email = f"prot_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post(
        "/auth/register",
        json={"organization_name": "Prot Org", "name": "Owner", "email": email, "password": PASSWORD},
    ).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    return email, tokens


def _auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _user(email: str) -> User:
    db = SessionLocal()
    try:
        return db.execute(select(User).where(User.email == email)).scalar_one()
    finally:
        db.close()


def _fail_n(client: TestClient, email: str, n: int) -> None:
    for _ in range(n):
        r = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-passwordxx"})
        assert r.status_code == 401


# --------------------------------------------------------------------------- #
# Lockout via login (§8) — preserves the generic 401 → 423 contract
# --------------------------------------------------------------------------- #
def test_failed_threshold_locks_account(client: TestClient) -> None:
    email, _ = _register(client)
    _fail_n(client, email, settings.PROTECTION_FAILED_THRESHOLD)
    # The next attempt — even correct — is locked.
    locked = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert locked.status_code == 423
    assert locked.json()["error"]["code"] == "ACCOUNT_LOCKED"

    user = _user(email)
    db = SessionLocal()
    try:
        lock = db.scalars(
            select(AccountLock).where(AccountLock.user_id == user.id)
        ).first()
        assert lock is not None and lock.status == AccountLockStatus.ACTIVE.value
        # Reason depends on the pattern: a plain threshold, or (because the shared test
        # IP has failed against many accounts) brute-force / credential-stuffing.
        assert lock.reason in (
            "FAILED_LOGIN_THRESHOLD", "BRUTE_FORCE_DETECTED", "CREDENTIAL_STUFFING_SUSPECTED"
        )
        # Both the new and the legacy lock event are recorded.
        for ev in (AuthEventType.ACCOUNT_LOCKED, AuthEventType.AUTH_LOGIN_LOCKED):
            assert db.scalars(
                select(SecurityEvent).where(SecurityEvent.event_type == ev.value, SecurityEvent.target_id == user.id)
            ).first() is not None
    finally:
        db.close()


def test_generic_message_does_not_reveal_lock_reason(client: TestClient) -> None:
    """§33: the failing attempts are generic; only the *locked* response differs."""
    email, _ = _register(client)
    for _ in range(settings.PROTECTION_FAILED_THRESHOLD):
        r = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-passwordxx"})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"
        assert "locked" not in r.json()["error"]["message"].lower()


def test_progressive_lockout_durations_escalate(client: TestClient) -> None:
    """§8: each successive lock is longer, and the 5th escalates to security review.
    Tested against the lockout service so the window-based failure count does not
    conflate rounds — the durations are the contract, not the trigger."""
    from app.identity.protection.enums import AccountLockReason
    from app.identity.protection.lockout import AccountLockoutService

    email, _ = _register(client)
    user_id = _user(email).id
    durations = settings.PROTECTION_LOCKOUT_DURATIONS

    db = SessionLocal()
    try:
        svc = AccountLockoutService(db)
        seen: list[float | None] = []
        for i in range(len(durations) + 1):
            user = db.get(User, user_id)
            result = svc.lock(user, reason=AccountLockReason.FAILED_LOGIN_THRESHOLD)
            lock = result.lock
            seen.append(
                (lock.expires_at - lock.locked_at).total_seconds() if lock.expires_at else None
            )
            # Force-expire so the next call creates a fresh (escalated) lock.
            lock.status = AccountLockStatus.EXPIRED.value
            db.flush()
        db.commit()
    finally:
        db.close()

    # 15m, 30m, 1h, 24h, then an indefinite (security-review) lock.
    for i, expected in enumerate(durations):
        assert seen[i] is not None and abs(seen[i] - expected) < 5
    assert seen[len(durations)] is None  # 5th lock → indefinite / security review

    # The account was parked for security review.
    assert _user(email).status == "SECURITY_REVIEW_REQUIRED"


def test_risk_event_recorded_on_successful_login(client: TestClient) -> None:
    email, _ = _register(client)
    user = _user(email)
    db = SessionLocal()
    try:
        assert db.scalars(
            select(IdentityRiskEvent).where(IdentityRiskEvent.user_id == user.id)
        ).first() is not None
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Admin console (§20, §24, §29)
# --------------------------------------------------------------------------- #
def test_admin_can_lock_and_unlock_a_user(client: TestClient) -> None:
    _owner, tokens = _register(client)
    owner = _user(_owner)
    # Create a member in the same org.
    from app.core.enums import UserRole
    from app.core.security import hash_password

    db = SessionLocal()
    try:
        member = User(
            organization_id=owner.organization_id, name="Member",
            email=f"m_{uuid.uuid4().hex[:8]}@example.com", password_hash=hash_password(PASSWORD),
            role=UserRole.VIEWER, is_active=True, status="ACTIVE",
        )
        db.add(member); db.commit(); db.refresh(member); mid = member.id; memail = member.email
    finally:
        db.close()

    lock = client.post(
        f"/api/v1/security/users/{mid}/lock",
        headers=_auth(tokens), json={"reason": "ADMIN_LOCKED", "comment": "test"},
    )
    assert lock.status_code == 200
    # Member cannot log in while locked.
    assert client.post("/api/v1/auth/login", json={"email": memail, "password": PASSWORD}).status_code == 423

    unlock = client.post(
        f"/api/v1/security/users/{mid}/unlock",
        headers=_auth(tokens), json={"reason": "resolved"},
    )
    assert unlock.status_code == 200
    # Now they can log in again.
    assert client.post("/api/v1/auth/login", json={"email": memail, "password": PASSWORD}).status_code == 200

    db = SessionLocal()
    try:
        assert db.scalars(
            select(SecurityEvent).where(
                SecurityEvent.event_type == AuthEventType.ACCOUNT_UNLOCKED.value,
                SecurityEvent.target_id == mid,
            )
        ).first() is not None
    finally:
        db.close()


def test_blocked_ip_denies_login_and_is_manageable(client: TestClient) -> None:
    _owner, tokens = _register(client)
    owner = _user(_owner)
    # A victim in the SAME org (so an org-scoped block on the shared test IP applies
    # here but not to other tests running in other orgs).
    from app.core.enums import UserRole
    from app.core.security import hash_password

    db = SessionLocal()
    try:
        victim = User(
            organization_id=owner.organization_id, name="Victim",
            email=f"vic_{uuid.uuid4().hex[:8]}@example.com", password_hash=hash_password(PASSWORD),
            role=UserRole.VIEWER, is_active=True, status="ACTIVE",
        )
        db.add(victim); db.commit(); vemail = victim.email
    finally:
        db.close()

    created = client.post(
        "/api/v1/security/blocked-ips",
        headers=_auth(tokens), json={"ip_address": "testclient", "reason": "abuse"},
    )
    assert created.status_code == 201
    block_id = created.json()["id"]

    # A login from the blocked IP (same org) is refused with IP_BLOCKED before the
    # password is even checked.
    denied = client.post("/api/v1/auth/login", json={"email": vemail, "password": PASSWORD})
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "IP_BLOCKED"

    # Unblock, and it works again.
    assert client.delete(f"/api/v1/security/blocked-ips/{block_id}", headers=_auth(tokens)).status_code == 204
    assert client.post("/api/v1/auth/login", json={"email": vemail, "password": PASSWORD}).status_code == 200


def test_protection_endpoints_require_permission(client: TestClient) -> None:
    assert client.get("/api/v1/security/account-locks").status_code in (401, 403)
    assert client.get("/api/v1/security/login-attempts").status_code in (401, 403)
    assert client.get("/api/v1/security/blocked-ips").status_code in (401, 403)
    assert client.get("/api/v1/security/account-protection/summary").status_code in (401, 403)


def test_summary_and_listing_endpoints(client: TestClient) -> None:
    email, tokens = _register(client)
    _fail_n(client, email, 2)
    summary = client.get("/api/v1/security/account-protection/summary", headers=_auth(tokens))
    assert summary.status_code == 200
    assert summary.json()["failed_logins_today"] >= 2

    attempts = client.get("/api/v1/security/login-attempts?success=false", headers=_auth(tokens))
    assert attempts.status_code == 200
    assert any(a["success"] is False for a in attempts.json())

    risk = client.get("/api/v1/security/risk-events", headers=_auth(tokens))
    assert risk.status_code == 200
