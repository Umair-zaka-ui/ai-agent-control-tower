"""Email delivery must never silently swallow a single-use link.

The bug this closes: with ``NOTIFICATIONS_ENABLED=false`` (the shipped dev default),
``send_email`` logged the *subject* and returned ``True``. The invitation went PENDING,
the UI showed it as sent, and the plaintext token — which exists only in that email, and
is stored as a SHA-256 hash — was gone for ever. The invitation could never be accepted.

Two fixes:

1. A **dev outbox**: when SMTP is off the whole message, link and all, is appended to a
   file. "Delivered to the configured sink" becomes true rather than convenient, and the
   link is recoverable.
2. The API tells the UI that delivery is disabled, so the Invitations panel can say so
   instead of implying an email is in flight.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.identity.email import EmailService
from app.main import app
from app.services import notification_service

OWNER_PASSWORD = "T3st!Passw0rd#Ok"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)


@pytest.fixture()
def outbox(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "dev-outbox.log"
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
    monkeypatch.setattr(settings, "EMAIL_DEV_OUTBOX_PATH", str(path))
    return path


def _register_org(client: TestClient) -> str:
    email = f"mail_{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        "/auth/register",
        json={"organization_name": "Mail Org", "name": "Owner", "email": email,
              "password": OWNER_PASSWORD},
    )
    assert resp.status_code == 201
    return resp.json()["access_token"]


# --------------------------------------------------------------------------- #
# The dev outbox
# --------------------------------------------------------------------------- #
def test_a_suppressed_email_is_written_to_the_dev_outbox(outbox: Path) -> None:
    delivered = notification_service.send_email(
        "ada@example.com", "You're invited", "Accept: http://localhost:5173/invite/inv_abc123"
    )
    assert delivered is True, "the message reached its configured sink"
    assert outbox.exists(), "the message vanished"

    written = outbox.read_text(encoding="utf-8")
    assert "ada@example.com" in written
    assert "You're invited" in written
    # The whole point: the single-use link survives.
    assert "inv_abc123" in written


def test_the_outbox_result_is_marked_suppressed_not_delivered(outbox: Path) -> None:
    """`sent` keeps the onboarding state machine moving; `suppressed` is the truth the
    UI needs so it does not tell a user to check an inbox that will stay empty."""
    result = EmailService().send_invitation(
        "ada@example.com",
        organization_name="Acme",
        role_name=None,
        invited_by_name="Owner",
        token="inv_abc123",
        expires_in_days=7,
    )
    assert result.sent is True
    assert result.suppressed is True

    assert "inv_abc123" in outbox.read_text(encoding="utf-8")


def test_an_invitation_link_is_always_recoverable_from_the_outbox(
    client: TestClient, outbox: Path
) -> None:
    """End to end: invite, then accept using only what the outbox recorded."""
    admin = _register_org(client)
    invitee = f"invitee_{uuid.uuid4().hex[:8]}@example.com"

    resp = client.post(
        "/api/v1/identity/invitations",
        headers={"Authorization": f"Bearer {admin}"},
        json={"email": invitee},
    )
    assert resp.status_code == 201

    import re

    match = re.search(r"/invite/(inv_[\w-]+)", outbox.read_text(encoding="utf-8"))
    assert match, "the invitation link was not recoverable"
    token = match.group(1)

    preview = client.get(f"/api/v1/identity/invitations/{token}")
    assert preview.status_code == 200
    assert preview.json()["email"] == invitee


def test_nothing_is_written_to_the_outbox_when_smtp_is_enabled(tmp_path, monkeypatch) -> None:
    """The outbox holds plaintext single-use tokens. It is a development artefact and
    must never be produced by a deployment that actually sends mail."""
    path = tmp_path / "dev-outbox.log"
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(settings, "EMAIL_DEV_OUTBOX_PATH", str(path))
    monkeypatch.setattr(settings, "SMTP_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "SMTP_PORT", 1)  # nothing is listening

    delivered = notification_service.send_email("ada@example.com", "s", "body inv_secret")

    assert delivered is False, "an SMTP failure must be reported, not swallowed"
    assert not path.exists(), "a token was written to disk by a mail-sending deployment"


def test_an_smtp_failure_leaves_the_account_registered_not_email_pending(
    client: TestClient, monkeypatch
) -> None:
    """`REGISTERED` is the state that means "mail is broken". It must be reachable."""
    from app.identity.models.enums import IdentityStatus

    monkeypatch.setattr(notification_service, "send_email", lambda *a, **k: False)

    admin = _register_org(client)
    invitee = f"invitee_{uuid.uuid4().hex[:8]}@example.com"
    created = client.post(
        "/api/v1/identity/invitations",
        headers={"Authorization": f"Bearer {admin}"},
        json={"email": invitee},
    )
    assert created.status_code == 201

    from app.core.database import SessionLocal
    from app.identity.models.registration import Invitation
    from app.identity.registration.tokens import generate_invitation_token

    plaintext, hashed = generate_invitation_token()
    db = SessionLocal()
    try:
        db.get(Invitation, uuid.UUID(created.json()["id"])).token_hash = hashed
        db.commit()
    finally:
        db.close()

    resp = client.post(
        "/api/v1/auth/register",
        json={"token": plaintext, "first_name": "Ada", "last_name": "L",
              "password": "Inv1tee!Passw0rd#Ok", "confirm_password": "Inv1tee!Passw0rd#Ok"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email_sent"] is False
    assert body["status"] == IdentityStatus.REGISTERED.value
    assert "could not send" in body["message"].lower()


# --------------------------------------------------------------------------- #
# The API tells the UI the truth
# --------------------------------------------------------------------------- #
def test_email_delivery_status_reports_disabled(client: TestClient, outbox: Path) -> None:
    admin = _register_org(client)
    resp = client.get(
        "/api/v1/identity/email-delivery", headers={"Authorization": f"Bearer {admin}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["outbox_path"] == str(outbox)


def test_email_delivery_status_reports_enabled(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
    admin = _register_org(client)
    resp = client.get(
        "/api/v1/identity/email-delivery", headers={"Authorization": f"Bearer {admin}"}
    )
    assert resp.json() == {"enabled": True, "outbox_path": None}


def test_email_delivery_status_needs_invitation_view(client: TestClient) -> None:
    """It reveals a filesystem path. Not for anonymous callers."""
    assert client.get("/api/v1/identity/email-delivery").status_code in (401, 403)
