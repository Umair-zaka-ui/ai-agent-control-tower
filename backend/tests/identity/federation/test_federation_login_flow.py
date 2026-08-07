"""Phase 2.3.1 tests — end-to-end OIDC/SAML login through
``FederationService``, against this platform's own real dev database
(never a mock) — the credential rule, session-issuance reuse, JIT
provisioning, and per-org scoping, all proven live.

Mirrors every prior Milestone 2 connector's own invocation-test
discipline: the *database* half is entirely real (``SessionLocal``/
``TestClient``); only the IdP's own HTTP endpoints (JWKS fetch, token
exchange) are monkeypatched, since no live IdP is reachable in this
environment — the same, explicitly stated coverage boundary every prior
sub-phase's own external-network calls used."""

from __future__ import annotations

import datetime
import time
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlalchemy import select

from app.core.database import SessionLocal
from app.identity.errors import IdentityError
from app.identity.federation import oidc as oidc_mod
from app.identity.federation import saml as saml_mod
from app.identity.federation.service import FederationService
from app.identity.models.federation import FederatedIdentity
from app.identity.models.session import UserSession
from app.main import app
from app.models.rbac import Role, UserRole as UserRoleLink
from app.models.user import User
from tests.identity.federation import _saml_fixtures as fx

OWNER_PASSWORD = "T3st!Passw0rd#Ok"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _register_org(client: TestClient, org_name: str) -> dict:
    email = f"fed_{uuid.uuid4().hex[:10]}@example.com"
    reg = client.post(
        "/auth/register",
        json={"organization_name": org_name, "name": "Owner", "email": email, "password": OWNER_PASSWORD},
    )
    assert reg.status_code == 201, reg.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": OWNER_PASSWORD}).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=headers).json()
    return {"headers": headers, "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"], "email": email}


def _admin_user(db, admin: dict) -> User:
    return db.get(User, uuid.UUID(admin["user_id"]))


def _oidc_config_kwargs(**overrides):
    base = {
        "protocol": "OIDC", "provider_type": "GENERIC_OIDC", "display_name": "Test OIDC",
        "configuration": {
            "issuer": "https://idp.example.com", "authorization_endpoint": "https://idp.example.com/auth",
            "token_endpoint": "https://idp.example.com/token", "jwks_uri": "https://idp.example.com/jwks",
            "client_id": "test-client-id", "algorithms": ["RS256"],
        },
        "jit_provisioning_enabled": True,
    }
    base.update(overrides)
    return base


def _saml_config_kwargs(cert, *, acs_url: str, sp_entity_id: str = "https://platform.example.com/sp", **overrides):
    base = {
        "protocol": "SAML", "provider_type": "GENERIC_SAML", "display_name": "Test SAML",
        "configuration": {
            "idp_entity_id": "https://idp.example.com", "idp_sso_url": "https://idp.example.com/sso",
            "idp_x509_cert": cert.cert_body_b64, "sp_entity_id": sp_entity_id, "acs_url": acs_url,
        },
        "jit_provisioning_enabled": True,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# AC-06 / AC-19 / AC-24 — OIDC login end to end, JIT-provisioning a new user
# --------------------------------------------------------------------------- #
def test_ac19_ac24_oidc_login_jit_provisions_a_new_user_and_issues_a_real_session(client, rsa_keypair, monkeypatch):
    admin = _register_org(client, "Fed OIDC Org")
    db = SessionLocal()
    try:
        actor = _admin_user(db, admin)
        org_id = actor.organization_id
        service = FederationService(db)
        config = service.create_config(actor, org_id, **_oidc_config_kwargs())

        redirect_uri = "https://platform.example.com/api/v1/auth/federation/x/callback"
        auth_url = service.start_oidc_login(org_id, config.id, redirect_uri=redirect_uri)
        query = parse_qs(urlsplit(auth_url).query)
        state, nonce = query["state"][0], query["nonce"][0]

        now = int(time.time())
        id_token = jose_jwt.encode(
            {
                "sub": "oidc-subject-new-user", "iss": config.configuration["issuer"],
                "aud": config.configuration["client_id"], "nonce": nonce, "iat": now, "exp": now + 300,
                "email": f"newhire_{uuid.uuid4().hex[:8]}@example.com", "name": "New Hire",
            },
            rsa_keypair["private_pem"], algorithm="RS256", headers={"kid": rsa_keypair["kid"]},
        )
        monkeypatch.setattr(oidc_mod, "exchange_code_for_id_token", lambda *a, **k: id_token)
        monkeypatch.setattr(oidc_mod, "fetch_jwks", lambda *a, **k: rsa_keypair["jwks"])

        result = service.handle_oidc_callback(
            org_id, config.id, code="fake-code", state=state, redirect_uri=redirect_uri,
        )
        assert result.is_new_user is True
        assert result.access_token and result.refresh_token

        # AC-19 -- a real session row exists, exactly the same kind local login creates.
        session = db.get(UserSession, result.session_id)
        assert session is not None
        assert session.login_method == "OIDC"

        # AC-02 -- linked via the stable subject id, not email.
        link = db.execute(
            select(FederatedIdentity).where(FederatedIdentity.federation_config_id == config.id)
        ).scalar_one()
        assert link.external_subject_id == "oidc-subject-new-user"
        assert link.user_id == uuid.UUID(result.context.identity_id)
    finally:
        db.rollback()
        db.close()


def test_ac03_a_federated_session_is_indistinguishable_from_a_local_one_via_me(client, rsa_keypair, monkeypatch):
    """AC-03 -- the access token issued by a federated login authenticates
    against the exact same `/api/v1/auth/me` endpoint local login uses,
    with no special-casing."""
    admin = _register_org(client, "Fed Indistinguishable Org")
    db = SessionLocal()
    try:
        actor = _admin_user(db, admin)
        org_id = actor.organization_id
        service = FederationService(db)
        config = service.create_config(actor, org_id, **_oidc_config_kwargs())

        redirect_uri = "https://platform.example.com/callback"
        auth_url = service.start_oidc_login(org_id, config.id, redirect_uri=redirect_uri)
        query = parse_qs(urlsplit(auth_url).query)
        state, nonce = query["state"][0], query["nonce"][0]

        now = int(time.time())
        email = f"samesession_{uuid.uuid4().hex[:8]}@example.com"
        id_token = jose_jwt.encode(
            {"sub": "oidc-subject-indist", "iss": config.configuration["issuer"],
             "aud": config.configuration["client_id"], "nonce": nonce, "iat": now, "exp": now + 300,
             "email": email, "name": "Indist User"},
            rsa_keypair["private_pem"], algorithm="RS256", headers={"kid": rsa_keypair["kid"]},
        )
        monkeypatch.setattr(oidc_mod, "exchange_code_for_id_token", lambda *a, **k: id_token)
        monkeypatch.setattr(oidc_mod, "fetch_jwks", lambda *a, **k: rsa_keypair["jwks"])
        result = service.handle_oidc_callback(org_id, config.id, code="c", state=state, redirect_uri=redirect_uri)
    finally:
        db.rollback()
        db.close()

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {result.access_token}"})
    assert me.status_code == 200, me.text
    assert me.json()["user"]["email"] == email


# --------------------------------------------------------------------------- #
# AC-01 / AC-05 — the credential rule
# --------------------------------------------------------------------------- #
def test_ac01_ac05_no_user_credential_from_the_idp_is_ever_persisted(client, rsa_keypair, monkeypatch):
    admin = _register_org(client, "Fed Credential Rule Org")
    db = SessionLocal()
    try:
        actor = _admin_user(db, admin)
        org_id = actor.organization_id
        service = FederationService(db)
        config = service.create_config(actor, org_id, **_oidc_config_kwargs())

        redirect_uri = "https://platform.example.com/callback"
        auth_url = service.start_oidc_login(org_id, config.id, redirect_uri=redirect_uri)
        query = parse_qs(urlsplit(auth_url).query)
        state, nonce = query["state"][0], query["nonce"][0]
        now = int(time.time())
        id_token = jose_jwt.encode(
            {"sub": "oidc-subject-nocred", "iss": config.configuration["issuer"],
             "aud": config.configuration["client_id"], "nonce": nonce, "iat": now, "exp": now + 300,
             "email": f"nocred_{uuid.uuid4().hex[:8]}@example.com", "name": "No Cred"},
            rsa_keypair["private_pem"], algorithm="RS256", headers={"kid": rsa_keypair["kid"]},
        )
        monkeypatch.setattr(oidc_mod, "exchange_code_for_id_token", lambda *a, **k: id_token)
        monkeypatch.setattr(oidc_mod, "fetch_jwks", lambda *a, **k: rsa_keypair["jwks"])
        result = service.handle_oidc_callback(org_id, config.id, code="c", state=state, redirect_uri=redirect_uri)

        user = db.get(User, uuid.UUID(result.context.identity_id))
        # The sentinel, never a real hash of anything the IdP sent.
        from app.core.security import is_unusable_password

        assert is_unusable_password(user.password_hash)

        link = db.execute(
            select(FederatedIdentity).where(FederatedIdentity.user_id == user.id)
        ).scalar_one()
        # No credential-shaped column exists on the model at all (structural
        # proof, not just "we didn't set one this time").
        column_names = {c.name for c in FederatedIdentity.__table__.columns}
        assert not any("password" in c or "secret" in c or "credential" in c for c in column_names)
    finally:
        db.rollback()
        db.close()


# --------------------------------------------------------------------------- #
# AC-20 — JIT disabled rejects an unprovisioned user
# --------------------------------------------------------------------------- #
def test_ac20_jit_disabled_rejects_an_unprovisioned_user(client, rsa_keypair, monkeypatch):
    from app.identity.errors import ErrorCode

    admin = _register_org(client, "Fed No JIT Org")
    db = SessionLocal()
    try:
        actor = _admin_user(db, admin)
        org_id = actor.organization_id
        service = FederationService(db)
        config = service.create_config(actor, org_id, **_oidc_config_kwargs(jit_provisioning_enabled=False))

        redirect_uri = "https://platform.example.com/callback"
        auth_url = service.start_oidc_login(org_id, config.id, redirect_uri=redirect_uri)
        query = parse_qs(urlsplit(auth_url).query)
        state, nonce = query["state"][0], query["nonce"][0]
        now = int(time.time())
        id_token = jose_jwt.encode(
            {"sub": "oidc-subject-no-jit", "iss": config.configuration["issuer"],
             "aud": config.configuration["client_id"], "nonce": nonce, "iat": now, "exp": now + 300,
             "email": f"nojit_{uuid.uuid4().hex[:8]}@example.com", "name": "No Jit"},
            rsa_keypair["private_pem"], algorithm="RS256", headers={"kid": rsa_keypair["kid"]},
        )
        monkeypatch.setattr(oidc_mod, "exchange_code_for_id_token", lambda *a, **k: id_token)
        monkeypatch.setattr(oidc_mod, "fetch_jwks", lambda *a, **k: rsa_keypair["jwks"])

        with pytest.raises(IdentityError) as excinfo:
            service.handle_oidc_callback(org_id, config.id, code="c", state=state, redirect_uri=redirect_uri)
        assert excinfo.value.code == ErrorCode.FEDERATION_USER_NOT_PROVISIONED
    finally:
        db.rollback()
        db.close()


def test_ac19_jit_disabled_still_links_an_existing_local_account_by_email(client, rsa_keypair, monkeypatch):
    """Linking to an EXISTING account is always permitted -- only creating
    a brand-new one is gated by jit_provisioning_enabled (see
    service.py's own module docstring)."""
    admin = _register_org(client, "Fed Existing Link Org")
    db = SessionLocal()
    try:
        actor = _admin_user(db, admin)
        org_id = actor.organization_id
        service = FederationService(db)
        config = service.create_config(actor, org_id, **_oidc_config_kwargs(jit_provisioning_enabled=False))

        existing_email = admin["email"]  # the org owner's own, already-existing account
        redirect_uri = "https://platform.example.com/callback"
        auth_url = service.start_oidc_login(org_id, config.id, redirect_uri=redirect_uri)
        query = parse_qs(urlsplit(auth_url).query)
        state, nonce = query["state"][0], query["nonce"][0]
        now = int(time.time())
        id_token = jose_jwt.encode(
            {"sub": "oidc-subject-existing-owner", "iss": config.configuration["issuer"],
             "aud": config.configuration["client_id"], "nonce": nonce, "iat": now, "exp": now + 300,
             "email": existing_email, "name": "Owner"},
            rsa_keypair["private_pem"], algorithm="RS256", headers={"kid": rsa_keypair["kid"]},
        )
        monkeypatch.setattr(oidc_mod, "exchange_code_for_id_token", lambda *a, **k: id_token)
        monkeypatch.setattr(oidc_mod, "fetch_jwks", lambda *a, **k: rsa_keypair["jwks"])

        result = service.handle_oidc_callback(org_id, config.id, code="c", state=state, redirect_uri=redirect_uri)
        assert result.is_new_user is False
        assert str(actor.id) == result.context.identity_id
    finally:
        db.rollback()
        db.close()


# --------------------------------------------------------------------------- #
# AC-23 — the state parameter prevents CSRF on the callback
# --------------------------------------------------------------------------- #
def test_ac23_a_forged_state_is_rejected_before_any_idp_call_is_made(client, rsa_keypair, monkeypatch):
    admin = _register_org(client, "Fed CSRF Org")
    db = SessionLocal()
    try:
        actor = _admin_user(db, admin)
        org_id = actor.organization_id
        service = FederationService(db)
        config = service.create_config(actor, org_id, **_oidc_config_kwargs())

        def _fail_if_called(*args, **kwargs):
            raise AssertionError("no IdP call should be attempted once state verification has already failed")

        monkeypatch.setattr(oidc_mod, "exchange_code_for_id_token", _fail_if_called)
        monkeypatch.setattr(oidc_mod, "fetch_jwks", _fail_if_called)

        with pytest.raises(IdentityError) as excinfo:
            service.handle_oidc_callback(
                org_id, config.id, code="c", state="a-completely-forged-state-value",
                redirect_uri="https://platform.example.com/callback",
            )
        from app.identity.errors import ErrorCode

        assert excinfo.value.code == ErrorCode.FEDERATION_STATE_INVALID
    finally:
        db.rollback()
        db.close()


def test_ac23_an_expired_state_is_rejected(client, monkeypatch):
    admin = _register_org(client, "Fed Expired State Org")
    db = SessionLocal()
    try:
        actor = _admin_user(db, admin)
        org_id = actor.organization_id
        service = FederationService(db)
        config = service.create_config(actor, org_id, **_oidc_config_kwargs())

        import datetime as _dt

        from jose import jwt as _jose_jwt

        from app.core.config import settings as _settings

        past = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=1)
        expired_state = _jose_jwt.encode(
            {"purpose": "oidc_state", "organization_id": str(org_id), "federation_config_id": str(config.id),
             "nonce": "n", "iat": int((past - _dt.timedelta(seconds=1)).timestamp()), "exp": int(past.timestamp())},
            _settings.JWT_SECRET_KEY, algorithm=_settings.JWT_ALGORITHM,
        )
        with pytest.raises(IdentityError) as excinfo:
            service.handle_oidc_callback(
                org_id, config.id, code="c", state=expired_state, redirect_uri="https://platform.example.com/callback",
            )
        from app.identity.errors import ErrorCode

        assert excinfo.value.code == ErrorCode.FEDERATION_STATE_INVALID
    finally:
        db.rollback()
        db.close()


# --------------------------------------------------------------------------- #
# AC-21 — per-org scoping
# --------------------------------------------------------------------------- #
def test_ac21_a_user_cannot_authenticate_against_a_different_orgs_config(client, rsa_keypair, monkeypatch):
    admin_a = _register_org(client, "Fed Org A")
    admin_b = _register_org(client, "Fed Org B")
    db = SessionLocal()
    try:
        actor_a = _admin_user(db, admin_a)
        service = FederationService(db)
        config_a = service.create_config(actor_a, actor_a.organization_id, **_oidc_config_kwargs())

        redirect_uri = "https://platform.example.com/callback"
        auth_url = service.start_oidc_login(actor_a.organization_id, config_a.id, redirect_uri=redirect_uri)
        query = parse_qs(urlsplit(auth_url).query)
        state = query["state"][0]

        # Attempt to use org A's own, validly-signed state against org B's id.
        with pytest.raises(IdentityError):
            service.handle_oidc_callback_by_state(
                uuid.UUID(admin_b["organization_id"]), code="c", state=state, redirect_uri=redirect_uri,
            )
    finally:
        db.rollback()
        db.close()


# --------------------------------------------------------------------------- #
# AC-17 / AC-18 — claim mapping + RBAC
# --------------------------------------------------------------------------- #
def test_ac17_ac18_a_mapped_group_claim_grants_the_configured_rbac_role(client, rsa_keypair, monkeypatch):
    admin = _register_org(client, "Fed Role Mapping Org")
    db = SessionLocal()
    try:
        actor = _admin_user(db, admin)
        org_id = actor.organization_id
        admin_role = db.execute(
            select(Role).where(Role.organization_id == org_id, Role.name == "ADMIN")
        ).scalar_one()

        service = FederationService(db)
        config = service.create_config(
            actor, org_id, **_oidc_config_kwargs(claim_mappings={"rules": [{"idp_value": "AI-Admins", "role_name": "ADMIN"}]}),
        )

        redirect_uri = "https://platform.example.com/callback"
        auth_url = service.start_oidc_login(org_id, config.id, redirect_uri=redirect_uri)
        query = parse_qs(urlsplit(auth_url).query)
        state, nonce = query["state"][0], query["nonce"][0]
        now = int(time.time())
        id_token = jose_jwt.encode(
            {"sub": "oidc-subject-mapped-admin", "iss": config.configuration["issuer"],
             "aud": config.configuration["client_id"], "nonce": nonce, "iat": now, "exp": now + 300,
             "email": f"mapped_{uuid.uuid4().hex[:8]}@example.com", "name": "Mapped Admin",
             "groups": ["AI-Admins"]},
            rsa_keypair["private_pem"], algorithm="RS256", headers={"kid": rsa_keypair["kid"]},
        )
        monkeypatch.setattr(oidc_mod, "exchange_code_for_id_token", lambda *a, **k: id_token)
        monkeypatch.setattr(oidc_mod, "fetch_jwks", lambda *a, **k: rsa_keypair["jwks"])

        result = service.handle_oidc_callback(org_id, config.id, code="c", state=state, redirect_uri=redirect_uri)
        user_id = uuid.UUID(result.context.identity_id)
        link = db.execute(
            select(UserRoleLink).where(UserRoleLink.user_id == user_id, UserRoleLink.role_id == admin_role.id)
        ).scalar_one_or_none()
        assert link is not None
        assert "identity.federation.manage" in result.context.permissions
    finally:
        db.rollback()
        db.close()


# --------------------------------------------------------------------------- #
# SAML end to end
# --------------------------------------------------------------------------- #
def test_ac19_saml_login_end_to_end_jit_provisions_a_new_user(client):
    admin = _register_org(client, "Fed SAML Org")
    db = SessionLocal()
    try:
        actor = _admin_user(db, admin)
        org_id = actor.organization_id
        cert = fx.generate_idp_certificate()
        acs_url = "https://platform.example.com/api/v1/auth/federation/x/saml/acs"
        service = FederationService(db)
        config = service.create_config(actor, org_id, **_saml_config_kwargs(cert, acs_url=acs_url))

        redirect_url = service.start_saml_login(org_id, config.id)
        query = parse_qs(urlsplit(redirect_url).query)
        relay_state = query["RelayState"][0]
        relay_claims = FederationService._verify_flow_token(relay_state, purpose="saml_relay_state")
        request_id = relay_claims["request_id"]

        now = datetime.datetime.now(datetime.timezone.utc)
        assertion_id = f"_assertion{uuid.uuid4().hex[:10]}"
        assertion = fx.build_assertion_xml(
            assertion_id=assertion_id, idp_entity_id=config.configuration["idp_entity_id"],
            sp_entity_id=config.configuration["sp_entity_id"], acs_url=acs_url, subject="saml-subject-new",
            in_response_to=request_id, not_before=now - datetime.timedelta(minutes=5),
            not_after=now + datetime.timedelta(minutes=5),
            attributes={"email": [f"samljit_{uuid.uuid4().hex[:8]}@example.com"], "name": ["SAML User"]},
        )
        response = fx.build_response_xml(
            response_id=f"_r{uuid.uuid4().hex[:10]}", in_response_to=request_id,
            idp_entity_id=config.configuration["idp_entity_id"], acs_url=acs_url, assertion=assertion,
        )
        fx.sign_element(response, element_id=assertion_id, cert=cert)
        request_data = saml_mod.build_request_data(
            https=True, http_host="platform.example.com",
            script_name="/api/v1/auth/federation/x/saml/acs",
            post_data={"SAMLResponse": fx.to_base64(response), "RelayState": relay_state},
        )

        result = service.handle_saml_acs(org_id, config.id, request_data=request_data, relay_state=relay_state)
        assert result.is_new_user is True

        session = db.get(UserSession, result.session_id)
        assert session.login_method == "SAML"
    finally:
        db.rollback()
        db.close()
