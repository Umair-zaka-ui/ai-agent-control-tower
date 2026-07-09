"""The login endpoint is adaptively rate limited (4.2.2.3.4 §10)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.config import settings
from app.core.database import SessionLocal
from app.identity.models.registration import RateLimitHit
from app.identity.protection.enums import RiskLevel
from app.identity.protection.rate_limit import _risk_level_from_failures
from app.identity.protection.policy import AdaptiveRateLimitService
from app.main import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _rate_limiting_on(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)


@pytest.fixture(autouse=True)
def _clean_buckets():
    db = SessionLocal()
    try:
        db.execute(delete(RateLimitHit))
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.execute(delete(RateLimitHit))
        db.commit()
    finally:
        db.close()


def test_risk_level_from_failures_tiers() -> None:
    assert _risk_level_from_failures(0) is RiskLevel.LOW
    assert _risk_level_from_failures(settings.PROTECTION_FAILED_THRESHOLD) is RiskLevel.HIGH
    assert _risk_level_from_failures(settings.PROTECTION_BRUTEFORCE_IP_THRESHOLD) is RiskLevel.SEVERE


def test_login_is_rate_limited_after_the_base_limit(client: TestClient) -> None:
    """A clean IP gets the base 5/min; the 6th sign-in attempt in the window is 429
    (TOO_MANY_ATTEMPTS), before any lockout — the limiter is genuinely wired to login."""
    base = settings.RATE_LIMIT_DEFAULT_REQUESTS
    email = f"rl_{uuid.uuid4().hex[:8]}@example.com"  # unknown account: never locks
    codes = [
        client.post("/api/v1/auth/login", json={"email": email, "password": "whatever12345"}).status_code
        for _ in range(base + 2)
    ]
    assert codes.count(429) >= 1, codes
    # The throttle uses the adaptive TOO_MANY_ATTEMPTS code.
    throttled = client.post("/api/v1/auth/login", json={"email": email, "password": "whatever12345"})
    assert throttled.status_code == 429
    assert throttled.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"


def test_a_risky_ip_gets_a_tighter_limit() -> None:
    """The effective limit drops as the IP looks more like an attacker (§10)."""
    base = settings.RATE_LIMIT_DEFAULT_REQUESTS
    assert AdaptiveRateLimitService.adjusted_limit(base, _risk_level_from_failures(0)) == base
    assert AdaptiveRateLimitService.adjusted_limit(
        base, _risk_level_from_failures(settings.PROTECTION_FAILED_THRESHOLD)
    ) < base
