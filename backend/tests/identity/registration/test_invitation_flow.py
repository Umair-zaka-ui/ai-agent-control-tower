"""Phase 4 Part 4.2.2.3.1 — invitation & registration flow (§21).

Unit + integration coverage for the acceptance criteria:

    invitation creation · invitation validation · registration validation
    email verification · duplicate invitation handling · expired invitation handling
    token hashing · full invitation flow · registration flow · verification flow
    audit event creation
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.identity.auth.enums import AuthEventType
from app.identity.models.enums import IdentityStatus, InvitationStatus, RegistrationMode
from app.identity.models.registration import EmailVerification, Invitation, UserProfile
from app.identity.models.security_event import SecurityEvent
from app.identity.registration.tokens import (
    generate_invitation_token,
    generate_verification_token,
    token_hash,
)
from app.main import app
from app.models.organization import Organization
from app.models.rbac import Role
from app.models.user import User

OWNER_PASSWORD = "T3st!Passw0rd#Ok"
INVITEE_PASSWORD = "Inv1tee!Passw0rd#Ok"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """The rate limiter is tested on its own. Here it would throttle the 6th request
    of an unrelated test and produce a confusing 429."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)


def _register_org(client: TestClient) -> tuple[str, str]:
    """Bootstrap an org + SUPER_ADMIN. Returns (owner_email, legacy_admin_token)."""
    email = f"owner_{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        "/auth/register",
        json={"organization_name": "Invite Org", "name": "Owner", "email": email,
              "password": OWNER_PASSWORD},
    )
    assert resp.status_code == 201
    return email, resp.json()["access_token"]


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _invitee_email() -> str:
    return f"invitee_{uuid.uuid4().hex[:10]}@example.com"


def _create_invitation(client: TestClient, admin: str, email: str, **body) -> dict:
    resp = client.post(
        "/api/v1/identity/invitations", headers=_h(admin), json={"email": email, **body}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _token_for(invitation_id: str) -> str:
    """Tests never see the plaintext token (it only exists in the email). Mint a known
    one directly against the row — exactly what the email link would carry."""
    plaintext, hashed = generate_invitation_token()
    db = SessionLocal()
    try:
        inv = db.get(Invitation, uuid.UUID(invitation_id))
        inv.token_hash = hashed
        db.commit()
    finally:
        db.close()
    return plaintext


def _verification_token_for(user_email: str) -> str:
    plaintext, hashed = generate_verification_token()
    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.email == user_email)).scalar_one()
        ev = db.execute(
            select(EmailVerification)
            .where(EmailVerification.user_id == user.id, EmailVerification.verified_at.is_(None))
            .order_by(EmailVerification.created_at.desc())
        ).scalars().first()
        assert ev is not None, "registration did not create a verification token"
        ev.verification_token_hash = hashed
        db.commit()
    finally:
        db.close()
    return plaintext


def _events(email: str, event: AuthEventType) -> list[SecurityEvent]:
    db = SessionLocal()
    try:
        rows = db.execute(
            select(SecurityEvent).where(SecurityEvent.event_type == event.value)
        ).scalars().all()
        return [e for e in rows if (e.meta or {}).get("target_email") == email]
    finally:
        db.close()


def _user(email: str) -> User | None:
    db = SessionLocal()
    try:
        return db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    finally:
        db.close()


# =========================================================================== #
# Unit: token hashing (§14, §21)
# =========================================================================== #
def test_tokens_are_random_prefixed_and_never_stored_in_plaintext() -> None:
    a, hash_a = generate_invitation_token()
    b, _ = generate_invitation_token()
    assert a != b, "tokens must be random"
    assert a.startswith("inv_") and b.startswith("inv_")
    assert hash_a != a and len(hash_a) == 64  # sha256 hex
    assert token_hash(a) == hash_a
    v, _ = generate_verification_token()
    assert v.startswith("vrf_")


def test_invitation_row_stores_only_the_hash(client: TestClient) -> None:
    _, admin = _register_org(client)
    email = _invitee_email()
    created = _create_invitation(client, admin, email)

    # The API response must never carry the token, not even a prefix.
    assert "token" not in created and "token_hash" not in created

    db = SessionLocal()
    try:
        inv = db.get(Invitation, uuid.UUID(created["id"]))
        assert inv.token_hash and len(inv.token_hash) == 64
        assert not inv.token_hash.startswith("inv_"), "plaintext token stored"
    finally:
        db.close()


# =========================================================================== #
# Invitation creation & validation (§21)
# =========================================================================== #
def test_create_invitation_emits_created_and_sent_events(client: TestClient) -> None:
    _, admin = _register_org(client)
    email = _invitee_email()
    created = _create_invitation(client, admin, email)

    assert created["status"] == InvitationStatus.PENDING.value
    assert created["email"] == email
    expires = datetime.fromisoformat(created["expires_at"])
    delta = expires - datetime.now(timezone.utc)
    assert abs(delta.total_seconds() - settings.INVITATION_TTL_SECONDS) < 60  # 7 days

    assert _events(email, AuthEventType.INVITATION_CREATED)
    assert _events(email, AuthEventType.INVITATION_SENT)


def test_public_preview_shows_org_role_and_expiry_but_no_internal_ids(client: TestClient) -> None:
    owner_email, admin = _register_org(client)
    email = _invitee_email()

    db = SessionLocal()
    try:
        owner = db.execute(select(User).where(User.email == owner_email)).scalar_one()
        role = db.execute(
            select(Role).where(Role.organization_id == owner.organization_id, Role.name == "ADMIN")
        ).scalars().first()
        role_id = str(role.id)
    finally:
        db.close()

    created = _create_invitation(client, admin, email, role_id=role_id)
    token = _token_for(created["id"])

    resp = client.get(f"/api/v1/identity/invitations/{token}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == email
    assert body["organization_name"] == "Invite Org"
    assert body["role_name"] == "ADMIN"
    assert body["invited_by_name"] == "Owner"
    assert body["expires_at"]
    # §9: the link must never expose internal IDs.
    assert "organization_id" not in body and "role_id" not in body


def test_unknown_token_is_404(client: TestClient) -> None:
    resp = client.get("/api/v1/identity/invitations/inv_definitely-not-a-real-token")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "INVITATION_NOT_FOUND"


def test_expired_invitation_is_410_and_is_materialised(client: TestClient) -> None:
    _, admin = _register_org(client)
    email = _invitee_email()
    created = _create_invitation(client, admin, email)
    token = _token_for(created["id"])

    db = SessionLocal()
    try:
        inv = db.get(Invitation, uuid.UUID(created["id"]))
        inv.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    resp = client.get(f"/api/v1/identity/invitations/{token}")
    assert resp.status_code == 410
    assert resp.json()["error"]["code"] == "INVITATION_EXPIRED"

    # The clock's verdict is *recorded*, so the admin list agrees with the accept path.
    db = SessionLocal()
    try:
        assert db.get(Invitation, uuid.UUID(created["id"])).status == InvitationStatus.EXPIRED.value
    finally:
        db.close()
    assert _events(email, AuthEventType.INVITATION_EXPIRED)


def test_cancelled_invitation_is_410_and_link_dies(client: TestClient) -> None:
    _, admin = _register_org(client)
    email = _invitee_email()
    created = _create_invitation(client, admin, email)
    token = _token_for(created["id"])

    resp = client.post(
        "/api/v1/identity/invitations/cancel",
        headers=_h(admin),
        json={"invitation_id": created["id"]},
    )
    assert resp.status_code == 200 and resp.json()["status"] == "CANCELLED"

    dead = client.get(f"/api/v1/identity/invitations/{token}")
    assert dead.status_code == 410
    assert dead.json()["error"]["code"] == "INVITATION_CANCELLED"
    assert _events(email, AuthEventType.INVITATION_CANCELLED)


def test_resend_rotates_the_token_so_the_old_link_dies(client: TestClient) -> None:
    """Otherwise a resend *adds* a valid link rather than replacing one, and
    "single use" quietly becomes "N uses"."""
    _, admin = _register_org(client)
    email = _invitee_email()
    created = _create_invitation(client, admin, email)
    old_token = _token_for(created["id"])
    assert client.get(f"/api/v1/identity/invitations/{old_token}").status_code == 200

    resp = client.post(
        "/api/v1/identity/invitations/resend",
        headers=_h(admin),
        json={"invitation_id": created["id"]},
    )
    assert resp.status_code == 200 and resp.json()["resent_count"] == 1

    assert client.get(f"/api/v1/identity/invitations/{old_token}").status_code == 404
    assert _events(email, AuthEventType.INVITATION_RESENT)


def test_duplicate_invitation_resends_instead_of_colliding(client: TestClient) -> None:
    """One live invitation per (org, email) — the partial unique index. Re-inviting is
    idempotent from the administrator's point of view."""
    _, admin = _register_org(client)
    email = _invitee_email()
    first = _create_invitation(client, admin, email)
    second = _create_invitation(client, admin, email)

    assert first["id"] == second["id"], "a second row was created"
    assert second["resent_count"] == 1

    db = SessionLocal()
    try:
        rows = db.execute(select(Invitation).where(Invitation.email == email)).scalars().all()
        assert len(rows) == 1
    finally:
        db.close()


def test_cannot_invite_an_existing_user(client: TestClient) -> None:
    owner_email, admin = _register_org(client)
    resp = client.post(
        "/api/v1/identity/invitations", headers=_h(admin), json={"email": owner_email}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "USER_ALREADY_EXISTS"


def test_invitation_is_scoped_to_the_organization(client: TestClient) -> None:
    _, admin_a = _register_org(client)
    _, admin_b = _register_org(client)
    created = _create_invitation(client, admin_a, _invitee_email())

    for path in ("resend", "cancel"):
        resp = client.post(
            f"/api/v1/identity/invitations/{path}",
            headers=_h(admin_b),
            json={"invitation_id": created["id"]},
        )
        assert resp.status_code == 404, f"cross-tenant {path} leaked"


def test_non_admin_cannot_invite(client: TestClient) -> None:
    """VIEWER holds neither invitation.manage nor invitation.view."""
    owner_email, admin = _register_org(client)
    email = _invitee_email()
    created = _create_invitation(client, admin, email)
    token = _token_for(created["id"])
    client.post(
        "/api/v1/auth/register",
        json={"token": token, "first_name": "Ada", "last_name": "Lovelace",
              "password": INVITEE_PASSWORD, "confirm_password": INVITEE_PASSWORD},
    )
    verify = _verification_token_for(email)
    client.post("/api/v1/auth/verify-email", json={"token": verify})

    viewer = client.post(
        "/auth/login", json={"email": email, "password": INVITEE_PASSWORD}
    ).json()["access_token"]

    assert client.post(
        "/api/v1/identity/invitations", headers=_h(viewer), json={"email": _invitee_email()}
    ).status_code == 403
    assert client.get("/api/v1/identity/invitations", headers=_h(viewer)).status_code == 403


# =========================================================================== #
# Registration (§8, §10, §11, §21)
# =========================================================================== #
def test_full_invitation_flow_creates_identity_and_profile(client: TestClient) -> None:
    _, admin = _register_org(client)
    email = _invitee_email()
    created = _create_invitation(client, admin, email)
    token = _token_for(created["id"])

    resp = client.post(
        "/api/v1/auth/register",
        json={
            "token": token,
            "first_name": "  Ada  ",       # trimmed
            "last_name": "Lovelace",
            "password": INVITEE_PASSWORD,
            "confirm_password": INVITEE_PASSWORD,
            "timezone": "Europe/Lisbon",
            "job_title": "Engineer",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == email
    assert body["status"] == IdentityStatus.EMAIL_PENDING.value
    assert body["requires_approval"] is False
    # Registration must NOT sign you in.
    assert "access_token" not in body and "refresh_token" not in body

    user = _user(email)
    assert user is not None
    assert user.status == IdentityStatus.EMAIL_PENDING.value
    assert user.is_active is False

    db = SessionLocal()
    try:
        profile = db.execute(
            select(UserProfile).where(UserProfile.user_id == user.id)
        ).scalar_one()
        assert profile.first_name == "Ada" and profile.last_name == "Lovelace"
        assert profile.job_title == "Engineer"
        assert profile.timezone == "Europe/Lisbon"
        assert profile.language == "en"  # initialize_preferences default
        invitation = db.get(Invitation, uuid.UUID(created["id"]))
        assert invitation.status == InvitationStatus.ACCEPTED.value
        assert invitation.accepted_at is not None
    finally:
        db.close()

    assert _events(email, AuthEventType.USER_REGISTERED)
    assert _events(email, AuthEventType.INVITATION_ACCEPTED)
    assert _events(email, AuthEventType.EMAIL_VERIFICATION_SENT)


def test_cannot_sign_in_before_verifying_email(client: TestClient) -> None:
    """Email verification is required before activation (acceptance criterion 5)."""
    _, admin = _register_org(client)
    email = _invitee_email()
    created = _create_invitation(client, admin, email)
    token = _token_for(created["id"])
    client.post(
        "/api/v1/auth/register",
        json={"token": token, "first_name": "Ada", "last_name": "L",
              "password": INVITEE_PASSWORD, "confirm_password": INVITEE_PASSWORD},
    )

    resp = client.post("/api/v1/auth/login", json={"email": email, "password": INVITEE_PASSWORD})
    assert resp.status_code == 403
    # Actionable: "verify your email", not "you are disabled".
    assert resp.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"


def test_verify_email_activates_and_permits_sign_in(client: TestClient) -> None:
    _, admin = _register_org(client)
    email = _invitee_email()
    created = _create_invitation(client, admin, email)
    token = _token_for(created["id"])
    client.post(
        "/api/v1/auth/register",
        json={"token": token, "first_name": "Ada", "last_name": "L",
              "password": INVITEE_PASSWORD, "confirm_password": INVITEE_PASSWORD},
    )

    verify = _verification_token_for(email)
    resp = client.post("/api/v1/auth/verify-email", json={"token": verify})
    assert resp.status_code == 200
    assert resp.json()["status"] == IdentityStatus.ACTIVE.value

    user = _user(email)
    assert user.status == IdentityStatus.ACTIVE.value and user.is_active is True

    login = client.post("/api/v1/auth/login", json={"email": email, "password": INVITEE_PASSWORD})
    assert login.status_code == 200

    assert _events(email, AuthEventType.EMAIL_VERIFIED)
    assert _events(email, AuthEventType.ACCOUNT_ACTIVATED)


def test_verification_token_is_single_use(client: TestClient) -> None:
    _, admin = _register_org(client)
    email = _invitee_email()
    created = _create_invitation(client, admin, email)
    client.post(
        "/api/v1/auth/register",
        json={"token": _token_for(created["id"]), "first_name": "Ada", "last_name": "L",
              "password": INVITEE_PASSWORD, "confirm_password": INVITEE_PASSWORD},
    )
    verify = _verification_token_for(email)
    assert client.post("/api/v1/auth/verify-email", json={"token": verify}).status_code == 200

    again = client.post("/api/v1/auth/verify-email", json={"token": verify})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "EMAIL_ALREADY_VERIFIED"


def test_expired_verification_token_is_410(client: TestClient) -> None:
    _, admin = _register_org(client)
    email = _invitee_email()
    created = _create_invitation(client, admin, email)
    client.post(
        "/api/v1/auth/register",
        json={"token": _token_for(created["id"]), "first_name": "Ada", "last_name": "L",
              "password": INVITEE_PASSWORD, "confirm_password": INVITEE_PASSWORD},
    )
    verify = _verification_token_for(email)

    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.email == email)).scalar_one()
        ev = db.execute(
            select(EmailVerification).where(EmailVerification.user_id == user.id)
        ).scalars().first()
        ev.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    resp = client.post("/api/v1/auth/verify-email", json={"token": verify})
    assert resp.status_code == 410
    assert resp.json()["error"]["code"] == "VERIFICATION_TOKEN_EXPIRED"


def test_invitation_token_is_single_use(client: TestClient) -> None:
    _, admin = _register_org(client)
    email = _invitee_email()
    created = _create_invitation(client, admin, email)
    token = _token_for(created["id"])
    body = {"token": token, "first_name": "Ada", "last_name": "L",
            "password": INVITEE_PASSWORD, "confirm_password": INVITEE_PASSWORD}
    assert client.post("/api/v1/auth/register", json=body).status_code == 201

    again = client.post("/api/v1/auth/register", json=body)
    assert again.status_code == 410
    assert again.json()["error"]["code"] == "INVITATION_ALREADY_USED"


def test_registration_uses_the_invitation_email_not_a_supplied_one(client: TestClient) -> None:
    """§11: the email comes from the invitation and cannot be changed. An attacker
    holding a link must not be able to register an arbitrary address into the org."""
    _, admin = _register_org(client)
    email = _invitee_email()
    created = _create_invitation(client, admin, email)
    token = _token_for(created["id"])

    resp = client.post(
        "/api/v1/auth/register",
        json={"token": token, "first_name": "Mal", "last_name": "Ory",
              "email": "attacker@evil.example",  # ignored: not in the schema
              "password": INVITEE_PASSWORD, "confirm_password": INVITEE_PASSWORD},
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == email
    assert _user("attacker@evil.example") is None


@pytest.mark.parametrize(
    "override,expected_field",
    [
        ({"first_name": "   "}, "first_name"),
        ({"last_name": ""}, "last_name"),
        ({"first_name": "x" * 101}, "first_name"),
        ({"confirm_password": "Different!Passw0rd"}, "confirm_password"),
        ({"password": "short", "confirm_password": "short"}, "password"),
    ],
)
def test_registration_validation(client: TestClient, override, expected_field) -> None:
    _, admin = _register_org(client)
    created = _create_invitation(client, admin, _invitee_email())
    body = {"token": _token_for(created["id"]), "first_name": "Ada", "last_name": "L",
            "password": INVITEE_PASSWORD, "confirm_password": INVITEE_PASSWORD, **override}
    resp = client.post("/api/v1/auth/register", json=body)
    assert resp.status_code == 422
    assert expected_field in resp.text


def test_weak_password_is_refused_by_the_policy_not_just_the_length_floor(client: TestClient) -> None:
    """`alllowercase123!` clears min_length=12 and must still be refused (ADR-0004)."""
    _, admin = _register_org(client)
    created = _create_invitation(client, admin, _invitee_email())
    resp = client.post(
        "/api/v1/auth/register",
        json={"token": _token_for(created["id"]), "first_name": "Ada", "last_name": "L",
              "password": "alllowercase123!", "confirm_password": "alllowercase123!"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


# =========================================================================== #
# Resend verification & enumeration safety (§14)
# =========================================================================== #
def test_resend_verification_never_reveals_whether_an_account_exists(client: TestClient) -> None:
    _, admin = _register_org(client)
    email = _invitee_email()
    created = _create_invitation(client, admin, email)
    client.post(
        "/api/v1/auth/register",
        json={"token": _token_for(created["id"]), "first_name": "Ada", "last_name": "L",
              "password": INVITEE_PASSWORD, "confirm_password": INVITEE_PASSWORD},
    )

    unregistered = client.post(
        "/api/v1/auth/resend-verification", json={"email": "nobody@example.com"}
    )
    pending = client.post("/api/v1/auth/resend-verification", json={"email": email})
    assert unregistered.status_code == pending.status_code == 200
    assert unregistered.json() == pending.json(), "response differs for an unknown address"

    # ...and once verified, still identical.
    client.post("/api/v1/auth/verify-email", json={"token": _verification_token_for(email)})
    verified = client.post("/api/v1/auth/resend-verification", json={"email": email})
    assert verified.json() == unregistered.json()


def test_resend_supersedes_the_previous_verification_token(client: TestClient) -> None:
    _, admin = _register_org(client)
    email = _invitee_email()
    created = _create_invitation(client, admin, email)
    client.post(
        "/api/v1/auth/register",
        json={"token": _token_for(created["id"]), "first_name": "Ada", "last_name": "L",
              "password": INVITEE_PASSWORD, "confirm_password": INVITEE_PASSWORD},
    )
    old = _verification_token_for(email)

    client.post("/api/v1/auth/resend-verification", json={"email": email})

    resp = client.post("/api/v1/auth/verify-email", json={"token": old})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_VERIFICATION_TOKEN"
    assert _user(email).status == IdentityStatus.EMAIL_PENDING.value


# =========================================================================== #
# Registration modes (§3)
# =========================================================================== #
def test_self_registration_is_disabled_by_default(client: TestClient) -> None:
    owner_email, _ = _register_org(client)
    org_id = str(_user(owner_email).organization_id)

    resp = client.post(
        "/api/v1/auth/register/self",
        json={"organization_id": org_id, "email": _invitee_email(), "first_name": "Ada",
              "last_name": "L", "password": INVITEE_PASSWORD, "confirm_password": INVITEE_PASSWORD},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "REGISTRATION_DISABLED"


def test_self_registration_requires_verification_then_admin_approval(client: TestClient) -> None:
    owner_email, admin = _register_org(client)
    org_id = _user(owner_email).organization_id

    db = SessionLocal()
    try:
        org = db.get(Organization, org_id)
        org.registration_mode = RegistrationMode.SELF_SERVICE.value
        db.commit()
    finally:
        db.close()

    email = _invitee_email()
    resp = client.post(
        "/api/v1/auth/register/self",
        json={"organization_id": str(org_id), "email": email, "first_name": "Ada",
              "last_name": "L", "password": INVITEE_PASSWORD, "confirm_password": INVITEE_PASSWORD},
    )
    assert resp.status_code == 201 and resp.json()["requires_approval"] is True

    # Verifying proves the address but does NOT activate: an admin must approve.
    verified = client.post(
        "/api/v1/auth/verify-email", json={"token": _verification_token_for(email)}
    )
    assert verified.json()["status"] == IdentityStatus.EMAIL_VERIFIED.value
    assert _user(email).status == IdentityStatus.EMAIL_VERIFIED.value

    blocked = client.post("/api/v1/auth/login", json={"email": email, "password": INVITEE_PASSWORD})
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "ACCOUNT_PENDING_APPROVAL"

    approved = client.post(
        f"/api/v1/identity/users/{_user(email).id}/approve", headers=_h(admin)
    )
    assert approved.status_code == 200
    assert _user(email).status == IdentityStatus.ACTIVE.value
    assert client.post(
        "/api/v1/auth/login", json={"email": email, "password": INVITEE_PASSWORD}
    ).status_code == 200


# =========================================================================== #
# Audit completeness (§13)
# =========================================================================== #
def test_every_srs_13_audit_event_is_reachable() -> None:
    """Guards against defining an event type nobody emits — a bug this codebase has
    produced repeatedly. An audit event that never fires is worse than none, because
    the documentation implies coverage that is not there."""
    import pathlib
    import re

    required = [
        AuthEventType.INVITATION_CREATED,
        AuthEventType.INVITATION_SENT,
        AuthEventType.INVITATION_ACCEPTED,
        AuthEventType.INVITATION_EXPIRED,
        AuthEventType.INVITATION_CANCELLED,
        AuthEventType.INVITATION_RESENT,
        AuthEventType.USER_REGISTERED,
        AuthEventType.EMAIL_VERIFICATION_SENT,
        AuthEventType.EMAIL_VERIFIED,
        AuthEventType.ACCOUNT_ACTIVATED,
        AuthEventType.ACCOUNT_PENDING_APPROVAL,
        AuthEventType.REGISTRATION_BLOCKED,
    ]
    app_dir = pathlib.Path(__file__).resolve().parents[3] / "app"
    sources = "\n".join(
        p.read_text(encoding="utf-8") for p in app_dir.rglob("*.py") if p.name != "enums.py"
    )
    dead = [e.name for e in required if not re.search(rf"AuthEventType\.{e.name}\b", sources)]
    assert not dead, f"audit event types defined but never emitted: {dead}"


def test_admin_only_mode_blocks_invitations(client: TestClient) -> None:
    """§3 mode 2: the administrator provisions accounts directly, so inviting is the
    wrong door. Allowing it would make the organization's stated policy a lie."""
    owner_email, admin = _register_org(client)
    org_id = _user(owner_email).organization_id

    db = SessionLocal()
    try:
        org = db.get(Organization, org_id)
        org.registration_mode = RegistrationMode.ADMIN_ONLY.value
        db.commit()
    finally:
        db.close()

    email = _invitee_email()
    resp = client.post("/api/v1/identity/invitations", headers=_h(admin), json={"email": email})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "REGISTRATION_DISABLED"
    assert _events(email, AuthEventType.REGISTRATION_BLOCKED)

    db = SessionLocal()
    try:
        assert db.execute(select(Invitation).where(Invitation.email == email)).scalars().first() is None
    finally:
        db.close()


def test_expired_invitation_emits_its_event_exactly_once(client: TestClient) -> None:
    """The event marks a *transition*, not a state. Without the guard, anyone can make
    us write unbounded audit rows by hitting a dead public link in a loop."""
    _, admin = _register_org(client)
    email = _invitee_email()
    created = _create_invitation(client, admin, email)
    token = _token_for(created["id"])

    db = SessionLocal()
    try:
        inv = db.get(Invitation, uuid.UUID(created["id"]))
        inv.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    for _ in range(4):
        assert client.get(f"/api/v1/identity/invitations/{token}").status_code == 410
    client.get("/api/v1/identity/invitations", headers=_h(admin))  # listing also materialises

    assert len(_events(email, AuthEventType.INVITATION_EXPIRED)) == 1
