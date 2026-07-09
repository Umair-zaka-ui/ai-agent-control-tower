"""Rate limiting on public onboarding endpoints (4.2.2.3.1 §19, criterion 8).

5 requests / minute / IP. The public endpoints are the platform's only unauthenticated
write surface; without this they are an open relay for enumeration and mail-bombing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.identity.models.registration import RateLimitHit
from app.identity.ratelimit import RateLimiter
from app.main import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _rate_limiting_on(monkeypatch):
    """This file *is* the rate-limit test, so it opts back in (the global test default
    is off — see tests/conftest.py). Runs after the conftest fixture, so it wins."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)


@pytest.fixture(autouse=True)
def _clean_buckets():
    """TestClient always presents the same client IP, so buckets leak between tests."""
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


# --------------------------------------------------------------------------- #
# Unit
# --------------------------------------------------------------------------- #
def test_limiter_allows_up_to_the_limit_then_refuses() -> None:
    db = SessionLocal()
    try:
        limiter = RateLimiter(db)
        bucket = f"unit:{uuid.uuid4()}"
        for i in range(5):
            decision = limiter.check(bucket, limit=5, window_seconds=60)
            assert decision.allowed, f"request {i + 1} of 5 was refused"
        refused = limiter.check(bucket, limit=5, window_seconds=60)
        assert refused.allowed is False
        assert refused.retry_after_seconds == 60
    finally:
        db.close()


def test_a_refused_request_still_counts_against_the_caller() -> None:
    """Otherwise a client hammering after a 429 silently resets its own window as old
    hits age out, and the limit never actually bites."""
    db = SessionLocal()
    try:
        limiter = RateLimiter(db)
        bucket = f"unit:{uuid.uuid4()}"
        for _ in range(7):
            limiter.check(bucket, limit=5, window_seconds=60)
        hits = db.execute(
            select(RateLimitHit).where(RateLimitHit.bucket == bucket)
        ).scalars().all()
        assert len(hits) == 7, "rejected requests were not recorded"
    finally:
        db.close()


def test_buckets_are_independent() -> None:
    db = SessionLocal()
    try:
        limiter = RateLimiter(db)
        a, b = f"a:{uuid.uuid4()}", f"b:{uuid.uuid4()}"
        for _ in range(5):
            limiter.check(a, limit=5, window_seconds=60)
        assert limiter.check(a, limit=5, window_seconds=60).allowed is False
        assert limiter.check(b, limit=5, window_seconds=60).allowed is True
    finally:
        db.close()


def test_hits_outside_the_window_do_not_count() -> None:
    db = SessionLocal()
    try:
        bucket = f"unit:{uuid.uuid4()}"
        old = datetime.now(timezone.utc) - timedelta(seconds=120)
        for _ in range(5):
            db.add(RateLimitHit(bucket=bucket, created_at=old))
        db.commit()
        assert RateLimiter(db).check(bucket, limit=5, window_seconds=60).allowed is True
    finally:
        db.close()


def test_sweep_deletes_only_old_hits() -> None:
    db = SessionLocal()
    try:
        bucket = f"unit:{uuid.uuid4()}"
        db.add(RateLimitHit(bucket=bucket, created_at=datetime.now(timezone.utc) - timedelta(hours=2)))
        db.add(RateLimitHit(bucket=bucket, created_at=datetime.now(timezone.utc)))
        db.commit()
        RateLimiter(db).sweep(older_than_seconds=3600)
        remaining = db.execute(
            select(RateLimitHit).where(RateLimitHit.bucket == bucket)
        ).scalars().all()
        assert len(remaining) == 1
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Integration: the public endpoints (§19)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/api/v1/auth/register",
         {"token": "inv_nope", "first_name": "A", "last_name": "B",
          "password": "T3st!Passw0rd#Ok", "confirm_password": "T3st!Passw0rd#Ok"}),
        ("post", "/api/v1/auth/verify-email", {"token": "vrf_nope"}),
        ("post", "/api/v1/auth/resend-verification", {"email": "nobody@example.com"}),
    ],
)
def test_public_write_endpoints_are_rate_limited(client: TestClient, method, path, body) -> None:
    codes = [getattr(client, method)(path, json=body).status_code for _ in range(6)]
    assert codes[-1] == 429, f"{path} is not rate limited: {codes}"
    assert 429 not in codes[:5], f"{path} throttled before the limit: {codes}"


def test_invitation_preview_is_rate_limited(client: TestClient) -> None:
    codes = [client.get("/api/v1/identity/invitations/inv_nope").status_code for _ in range(6)]
    assert codes[-1] == 429
    assert 429 not in codes[:5]


def test_429_carries_retry_after(client: TestClient) -> None:
    """A client cannot behave correctly without it."""
    for _ in range(5):
        client.post("/api/v1/auth/resend-verification", json={"email": "x@example.com"})
    resp = client.post("/api/v1/auth/resend-verification", json={"email": "x@example.com"})
    assert resp.status_code == 429
    assert resp.headers.get("retry-after") == str(settings.RATE_LIMIT_DEFAULT_WINDOW_SECONDS)
    assert resp.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"


def test_the_limit_is_per_endpoint_not_global(client: TestClient) -> None:
    """Exhausting `resend-verification` must not lock a user out of `verify-email`."""
    for _ in range(6):
        client.post("/api/v1/auth/resend-verification", json={"email": "x@example.com"})
    other = client.post("/api/v1/auth/verify-email", json={"token": "vrf_nope"})
    assert other.status_code != 429


def test_authenticated_endpoints_are_not_rate_limited(client: TestClient) -> None:
    """The limit protects the *public* surface. Throttling an authenticated dashboard
    to 5 requests/minute would break the product."""
    email = f"rl_{uuid.uuid4().hex[:8]}@example.com"
    token = client.post(
        "/auth/register",
        json={"organization_name": "RL", "name": "O", "email": email,
              "password": "T3st!Passw0rd#Ok"},
    ).json()["access_token"]
    codes = [
        client.get("/api/v1/identity/invitations", headers={"Authorization": f"Bearer {token}"}).status_code
        for _ in range(8)
    ]
    assert 429 not in codes


def test_disabling_the_limiter_is_honoured(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    codes = [
        client.post("/api/v1/auth/resend-verification", json={"email": "x@example.com"}).status_code
        for _ in range(8)
    ]
    assert 429 not in codes
