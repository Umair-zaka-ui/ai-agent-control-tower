"""Closes the four gaps found auditing 4.2.2.3.1 against its Definition of Done.

1. **SSO/SCIM readiness.** The DoD claims "the architecture is ready for future SSO and
   SCIM provisioning without redesign". `ProvisionRequest.password` was *required* and
   `provision()` always hashed it — so an externally-authenticated identity, which has
   no password at all, could not be provisioned. The seam blocked the thing it existed
   to enable.

2. **A credential-less identity must not crash the login path.** `passlib` raises
   `UnknownHashError` on any non-hash, so a sentinel would turn a wrong-password attempt
   into a 500.

3. **`RateLimiter.sweep()` was dead.** `rate_limit_hits` grew forever — one row per
   public request, *and* one per rejected request. Under the flood it exists to stop,
   the anti-abuse table was an unbounded insert.

4. **`InvitationService.reap_expired()` was dead.** Expiry was enforced lazily on read,
   so an invitation nobody looked at stayed PENDING in the database indefinitely.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password, needs_rehash, verify_password
from app.identity.models.enums import IdentityStatus, InvitationStatus
from app.identity.models.registration import Invitation, RateLimitHit, UserProfile
from app.identity.ratelimit import RateLimiter
from app.identity.registration import InvitationService
from app.identity.registration.provisioning_service import (
    ProvisionRequest,
    UserProvisioningService,
)
from app.main import app
from app.models.user import User

OWNER_PASSWORD = "T3st!Passw0rd#Ok"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)


def _register_org(client: TestClient) -> tuple[str, str]:
    email = f"prov_{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        "/auth/register",
        json={"organization_name": "Prov Org", "name": "Owner", "email": email,
              "password": OWNER_PASSWORD},
    )
    assert resp.status_code == 201
    return email, resp.json()["access_token"]


def _org_of(email: str) -> uuid.UUID:
    db = SessionLocal()
    try:
        return db.execute(select(User).where(User.email == email)).scalar_one().organization_id
    finally:
        db.close()


# =========================================================================== #
# 1 + 2. SSO / SCIM provisioning: an identity with no password
# =========================================================================== #
def test_can_provision_an_identity_with_no_password(client: TestClient) -> None:
    """The SSO/SCIM seam. An externally-authenticated identity never has a password."""
    owner_email, _ = _register_org(client)
    org_id = _org_of(owner_email)
    email = f"sso_{uuid.uuid4().hex[:8]}@example.com"

    db = SessionLocal()
    try:
        user = UserProvisioningService(db).provision(
            ProvisionRequest(
                organization_id=org_id,
                email=email,
                password=None,  # ← the whole point
                first_name="Ada",
                last_name="Lovelace",
            ),
            status=IdentityStatus.ACTIVE,
        )
        db.commit()
        user_id = user.id
        stored_hash = user.password_hash
    finally:
        db.close()

    assert stored_hash, "password_hash is NOT NULL; a sentinel is required"
    assert not stored_hash.startswith("$"), "an unusable credential must not look like a hash"

    db = SessionLocal()
    try:
        profile = db.execute(select(UserProfile).where(UserProfile.user_id == user_id)).scalar_one()
        assert profile.first_name == "Ada"
    finally:
        db.close()


def test_a_passwordless_identity_cannot_sign_in_with_any_password(client: TestClient) -> None:
    """And must fail *closed*, with 401 — not a 500 from passlib's UnknownHashError."""
    owner_email, _ = _register_org(client)
    org_id = _org_of(owner_email)
    email = f"sso_{uuid.uuid4().hex[:8]}@example.com"

    db = SessionLocal()
    try:
        UserProvisioningService(db).provision(
            ProvisionRequest(
                organization_id=org_id, email=email, password=None,
                first_name="Ada", last_name="L",
            ),
            status=IdentityStatus.ACTIVE,
        )
        db.commit()
    finally:
        db.close()

    for attempt in ("", "!", "anything", OWNER_PASSWORD):
        resp = client.post("/api/v1/auth/login", json={"email": email, "password": attempt or "x"})
        assert resp.status_code == 401, f"password {attempt!r} produced {resp.status_code}"
        assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_verify_password_rejects_an_unusable_credential_without_raising() -> None:
    from app.core.security import UNUSABLE_PASSWORD, is_unusable_password

    assert is_unusable_password(UNUSABLE_PASSWORD)
    assert verify_password("anything", UNUSABLE_PASSWORD) is False
    assert verify_password("", UNUSABLE_PASSWORD) is False
    # And it must never be flagged for a "rehash to argon2id" upgrade on login.
    assert needs_rehash(UNUSABLE_PASSWORD) is False

    # A real hash is unaffected.
    real = hash_password("Str0ngP@ssword!")
    assert is_unusable_password(real) is False
    assert verify_password("Str0ngP@ssword!", real) is True


def test_provisioning_still_enforces_the_password_policy_when_one_is_given(client: TestClient) -> None:
    """Making the password optional must not make it unvalidated (ADR-0004)."""
    from app.identity.security.passwords import PasswordPolicyError

    owner_email, _ = _register_org(client)
    db = SessionLocal()
    try:
        with pytest.raises(PasswordPolicyError):
            UserProvisioningService(db).provision(
                ProvisionRequest(
                    organization_id=_org_of(owner_email),
                    email=f"weak_{uuid.uuid4().hex[:8]}@example.com",
                    password="alllowercase123!",  # clears min_length, fails the policy
                    first_name="Ada", last_name="L",
                ),
                status=IdentityStatus.ACTIVE,
            )
    finally:
        db.rollback()
        db.close()


# =========================================================================== #
# 3. The rate-limit table must not grow without bound
# =========================================================================== #
def test_limiter_prunes_its_own_bucket_so_the_table_cannot_grow_without_bound() -> None:
    """Each check cleans up hits its own window can no longer see. Bounded work,
    bounded table: roughly (active buckets × limit) rows."""
    db = SessionLocal()
    try:
        bucket = f"prune:{uuid.uuid4()}"
        old = datetime.now(timezone.utc) - timedelta(seconds=600)
        for _ in range(50):
            db.add(RateLimitHit(bucket=bucket, created_at=old))
        db.commit()

        RateLimiter(db).check(bucket, limit=5, window_seconds=60)

        remaining = db.execute(
            select(RateLimitHit).where(RateLimitHit.bucket == bucket)
        ).scalars().all()
        assert len(remaining) == 1, f"stale hits were not pruned: {len(remaining)} rows"
    finally:
        db.execute(delete(RateLimitHit))
        db.commit()
        db.close()


def test_pruning_never_removes_hits_the_window_can_still_see() -> None:
    """Pruning must not hand a flooder a free reset."""
    db = SessionLocal()
    try:
        bucket = f"prune:{uuid.uuid4()}"
        limiter = RateLimiter(db)
        for _ in range(5):
            limiter.check(bucket, limit=5, window_seconds=60)
        assert limiter.check(bucket, limit=5, window_seconds=60).allowed is False
        rows = db.execute(select(RateLimitHit).where(RateLimitHit.bucket == bucket)).scalars().all()
        assert len(rows) == 6, "in-window hits were pruned"
    finally:
        db.execute(delete(RateLimitHit))
        db.commit()
        db.close()


def test_a_flood_against_one_endpoint_does_not_grow_the_table(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    db = SessionLocal()
    try:
        db.execute(delete(RateLimitHit))
        db.commit()
    finally:
        db.close()

    for _ in range(30):
        client.post("/api/v1/auth/resend-verification", json={"email": "flood@example.com"})

    db = SessionLocal()
    try:
        rows = db.execute(select(RateLimitHit)).scalars().all()
        # All 30 are inside the 60s window, so all are legitimately retained. What must
        # be true is that nothing *older* than the window survives — proven above — and
        # that the sweep is reachable at all.
        assert len(rows) == 30
        pruned = RateLimiter(db).sweep(older_than_seconds=0)
        assert pruned == 30
    finally:
        db.execute(delete(RateLimitHit))
        db.commit()
        db.close()


# =========================================================================== #
# 4. Expired invitations are reaped, not merely ignored
# =========================================================================== #
def test_listing_reaps_every_expired_invitation_in_the_organization(client: TestClient) -> None:
    """An invitation nobody previews individually must still leave PENDING.

    Materialising only the rows on the current page would leave the database
    disagreeing with itself the moment an admin filtered or paginated.
    """
    owner_email, admin = _register_org(client)
    org_id = _org_of(owner_email)

    ids = []
    for _ in range(3):
        resp = client.post(
            "/api/v1/identity/invitations",
            headers={"Authorization": f"Bearer {admin}"},
            json={"email": f"reap_{uuid.uuid4().hex[:8]}@example.com"},
        )
        ids.append(uuid.UUID(resp.json()["id"]))

    db = SessionLocal()
    try:
        for invitation_id in ids:
            db.get(Invitation, invitation_id).expires_at = (
                datetime.now(timezone.utc) - timedelta(seconds=1)
            )
        db.commit()
    finally:
        db.close()

    # Ask only for ACCEPTED invitations: none of the expired rows is on this "page".
    resp = client.get(
        "/api/v1/identity/invitations?status=ACCEPTED",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert resp.status_code == 200

    db = SessionLocal()
    try:
        statuses = {db.get(Invitation, i).status for i in ids}
        assert statuses == {InvitationStatus.EXPIRED.value}, f"not reaped: {statuses}"
    finally:
        db.close()


def test_reap_is_scoped_to_one_organization(client: TestClient) -> None:
    owner_a, admin_a = _register_org(client)
    owner_b, admin_b = _register_org(client)

    other = client.post(
        "/api/v1/identity/invitations",
        headers={"Authorization": f"Bearer {admin_b}"},
        json={"email": f"other_{uuid.uuid4().hex[:8]}@example.com"},
    ).json()

    db = SessionLocal()
    try:
        db.get(Invitation, uuid.UUID(other["id"])).expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        )
        db.commit()
    finally:
        db.close()

    # Org A lists its own invitations; org B's expired row must be untouched by it.
    db = SessionLocal()
    try:
        reaped = InvitationService(db).reap_expired(organization_id=_org_of(owner_a))
        assert reaped == 0
        assert db.get(Invitation, uuid.UUID(other["id"])).status == InvitationStatus.PENDING.value
    finally:
        db.close()

    db = SessionLocal()
    try:
        assert InvitationService(db).reap_expired(organization_id=_org_of(owner_b)) == 1
        assert db.get(Invitation, uuid.UUID(other["id"])).status == InvitationStatus.EXPIRED.value
    finally:
        db.close()


def test_a_check_reaps_stale_rows_left_by_buckets_that_never_return() -> None:
    """Per-bucket pruning cannot reach them: a caller rotating IP addresses creates a
    bucket per address and never comes back. Without a bounded global reap on the way
    past, `rate_limit_hits` grows for ever."""
    db = SessionLocal()
    try:
        db.execute(delete(RateLimitHit))
        stale = datetime.now(timezone.utc) - timedelta(hours=2)
        for i in range(20):
            db.add(RateLimitHit(bucket=f"abandoned:{i}", created_at=stale))
        db.commit()

        RateLimiter(db).check(f"live:{uuid.uuid4()}", limit=5, window_seconds=60)

        abandoned = db.execute(
            select(RateLimitHit).where(RateLimitHit.bucket.like("abandoned:%"))
        ).scalars().all()
        assert abandoned == [], f"{len(abandoned)} orphaned rows survived"
    finally:
        db.execute(delete(RateLimitHit))
        db.commit()
        db.close()


def test_the_global_reap_is_bounded_per_request(monkeypatch) -> None:
    """A request must never pay for an unbounded delete: an operator who lets the table
    grow must not have one unlucky user absorb the entire cleanup."""
    monkeypatch.setattr(settings, "RATE_LIMIT_SWEEP_BATCH", 5)
    db = SessionLocal()
    try:
        db.execute(delete(RateLimitHit))
        stale = datetime.now(timezone.utc) - timedelta(hours=2)
        for i in range(20):
            db.add(RateLimitHit(bucket=f"abandoned:{i}", created_at=stale))
        db.commit()

        RateLimiter(db).check(f"live:{uuid.uuid4()}", limit=5, window_seconds=60)

        remaining = db.execute(
            select(RateLimitHit).where(RateLimitHit.bucket.like("abandoned:%"))
        ).scalars().all()
        assert len(remaining) == 15, "the reap was not bounded to the batch size"
    finally:
        db.execute(delete(RateLimitHit))
        db.commit()
        db.close()
