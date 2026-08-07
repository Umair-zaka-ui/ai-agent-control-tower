"""Phase 2.3.1 tests — federation configuration admin API
(``/api/v1/identity/federation/configs``): permission gating, per-org
isolation, provider coverage, and the credential-protection structural
proof, all against real HTTP requests through the real app."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app

OWNER_PASSWORD = "T3st!Passw0rd#Ok"
CONFIGS_URL = "/api/v1/identity/federation/configs"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _register_org(client: TestClient, org_name: str) -> dict:
    email = f"fedcfg_{uuid.uuid4().hex[:10]}@example.com"
    reg = client.post(
        "/auth/register",
        json={"organization_name": org_name, "name": "Owner", "email": email, "password": OWNER_PASSWORD},
    )
    assert reg.status_code == 201, reg.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": OWNER_PASSWORD}).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=headers).json()
    return {"headers": headers, "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"], "email": email}


def _make_viewer(client: TestClient, admin: dict) -> dict:
    email = f"fedcfgv_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post(
        "/api/v1/identity/users", headers=admin["headers"],
        json={"email": email, "display_name": "Viewer", "password": OWNER_PASSWORD, "role": "VIEWER",
              "organization_id": admin["organization_id"]},
    )
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": OWNER_PASSWORD}).json()
    return {"headers": {"Authorization": f"Bearer {tokens['access_token']}"}}


def _oidc_payload(**overrides):
    base = {
        "protocol": "OIDC", "provider_type": "GENERIC_OIDC", "display_name": "My OIDC IdP",
        "configuration": {
            "issuer": "https://idp.example.com", "authorization_endpoint": "https://idp.example.com/auth",
            "token_endpoint": "https://idp.example.com/token", "jwks_uri": "https://idp.example.com/jwks",
            "client_id": "client-abc",
        },
        "client_secret": "super-secret-client-value-9f8e7d",
        "jit_provisioning_enabled": True,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# AC-24 — identity-admin permission enforced
# --------------------------------------------------------------------------- #
def test_ac24_creating_a_config_requires_the_manage_permission(client):
    admin = _register_org(client, "Fed CRUD Org")
    viewer = _make_viewer(client, admin)
    r = client.post(CONFIGS_URL, headers=viewer["headers"], json=_oidc_payload())
    assert r.status_code == 403, r.text


def test_ac24_an_admin_can_create_list_get_and_delete_a_config(client):
    admin = _register_org(client, "Fed CRUD Org 2")
    create = client.post(CONFIGS_URL, headers=admin["headers"], json=_oidc_payload())
    assert create.status_code == 201, create.text
    config_id = create.json()["id"]

    listing = client.get(CONFIGS_URL, headers=admin["headers"])
    assert listing.status_code == 200
    assert any(c["id"] == config_id for c in listing.json())

    got = client.get(f"{CONFIGS_URL}/{config_id}", headers=admin["headers"])
    assert got.status_code == 200
    assert got.json()["display_name"] == "My OIDC IdP"

    deleted = client.delete(f"{CONFIGS_URL}/{config_id}", headers=admin["headers"])
    assert deleted.status_code == 204

    missing = client.get(f"{CONFIGS_URL}/{config_id}", headers=admin["headers"])
    assert missing.status_code == 404


# --------------------------------------------------------------------------- #
# AC-21 / AC-24 — cross-org isolation, indistinguishable from not-found
# --------------------------------------------------------------------------- #
def test_ac21_a_config_belonging_to_a_different_org_is_a_plain_404(client):
    admin_a = _register_org(client, "Fed CRUD Org A")
    admin_b = _register_org(client, "Fed CRUD Org B")
    create = client.post(CONFIGS_URL, headers=admin_a["headers"], json=_oidc_payload())
    config_id = create.json()["id"]

    cross = client.get(f"{CONFIGS_URL}/{config_id}", headers=admin_b["headers"])
    assert cross.status_code == 404

    cross_delete = client.delete(f"{CONFIGS_URL}/{config_id}", headers=admin_b["headers"])
    assert cross_delete.status_code == 404


def test_ac21_listing_only_shows_the_callers_own_org(client):
    admin_a = _register_org(client, "Fed CRUD Org C")
    admin_b = _register_org(client, "Fed CRUD Org D")
    client.post(CONFIGS_URL, headers=admin_a["headers"], json=_oidc_payload(display_name="Org A's IdP"))
    client.post(CONFIGS_URL, headers=admin_b["headers"], json=_oidc_payload(display_name="Org B's IdP"))

    listing_a = client.get(CONFIGS_URL, headers=admin_a["headers"]).json()
    listing_b = client.get(CONFIGS_URL, headers=admin_b["headers"]).json()
    assert {c["display_name"] for c in listing_a} == {"Org A's IdP"}
    assert {c["display_name"] for c in listing_b} == {"Org B's IdP"}


# --------------------------------------------------------------------------- #
# AC-05 / AC-25 — the SP's own client secret is protected
# --------------------------------------------------------------------------- #
def test_ac05_the_client_secret_is_never_returned_by_the_api(client):
    admin = _register_org(client, "Fed CRUD Secret Org")
    create = client.post(CONFIGS_URL, headers=admin["headers"], json=_oidc_payload())
    body = create.json()
    assert "client_secret" not in body
    assert "encrypted_client_secret" not in body
    assert body["has_client_secret"] is True
    assert "super-secret-client-value-9f8e7d" not in create.text


def test_ac05_the_client_secret_is_encrypted_at_rest(client):
    admin = _register_org(client, "Fed CRUD Secret Org 2")
    create = client.post(CONFIGS_URL, headers=admin["headers"], json=_oidc_payload())
    config_id = create.json()["id"]

    from app.identity.models.federation import FederationConfig

    db = SessionLocal()
    try:
        row = db.get(FederationConfig, uuid.UUID(config_id))
        assert row.encrypted_client_secret is not None
        assert "super-secret-client-value-9f8e7d" not in row.encrypted_client_secret
    finally:
        db.close()


def test_ac25_updating_the_config_requires_the_manage_permission(client):
    admin = _register_org(client, "Fed CRUD Update Org")
    viewer = _make_viewer(client, admin)
    create = client.post(CONFIGS_URL, headers=admin["headers"], json=_oidc_payload())
    config_id = create.json()["id"]

    r = client.put(
        f"{CONFIGS_URL}/{config_id}", headers=viewer["headers"],
        json={"configuration": {"issuer": "https://attacker-controlled.example.com",
                                 "authorization_endpoint": "https://attacker-controlled.example.com/auth",
                                 "token_endpoint": "https://attacker-controlled.example.com/token",
                                 "jwks_uri": "https://attacker-controlled.example.com/jwks",
                                 "client_id": "client-abc"}},
    )
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# AC-22 — Entra ID, Okta, generic OIDC, generic SAML all configurable
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("provider_type,protocol,configuration", [
    ("ENTRA_ID", "OIDC", {
        "issuer": "https://login.microsoftonline.com/tenant-id/v2.0",
        "authorization_endpoint": "https://login.microsoftonline.com/tenant-id/oauth2/v2.0/authorize",
        "token_endpoint": "https://login.microsoftonline.com/tenant-id/oauth2/v2.0/token",
        "jwks_uri": "https://login.microsoftonline.com/tenant-id/discovery/v2.0/keys",
        "client_id": "entra-client-id",
    }),
    ("OKTA", "OIDC", {
        "issuer": "https://dev-123456.okta.com", "authorization_endpoint": "https://dev-123456.okta.com/oauth2/v1/authorize",
        "token_endpoint": "https://dev-123456.okta.com/oauth2/v1/token", "jwks_uri": "https://dev-123456.okta.com/oauth2/v1/keys",
        "client_id": "okta-client-id",
    }),
    ("GENERIC_OIDC", "OIDC", {
        "issuer": "https://generic-idp.example.com", "authorization_endpoint": "https://generic-idp.example.com/auth",
        "token_endpoint": "https://generic-idp.example.com/token", "jwks_uri": "https://generic-idp.example.com/jwks",
        "client_id": "generic-client-id",
    }),
    ("GENERIC_SAML", "SAML", {
        "idp_entity_id": "https://generic-saml-idp.example.com", "idp_sso_url": "https://generic-saml-idp.example.com/sso",
        "idp_x509_cert": "MIIB...dummy...cert==", "sp_entity_id": "https://platform.example.com/sp",
        "acs_url": "https://platform.example.com/api/v1/auth/federation/x/saml/acs",
    }),
])
def test_ac22_each_named_provider_type_can_be_configured(client, provider_type, protocol, configuration):
    admin = _register_org(client, f"Fed Provider {provider_type} Org")
    r = client.post(CONFIGS_URL, headers=admin["headers"], json={
        "protocol": protocol, "provider_type": provider_type, "display_name": f"{provider_type} config",
        "configuration": configuration,
    })
    assert r.status_code == 201, r.text
    assert r.json()["provider_type"] == provider_type


def test_a_config_missing_required_fields_is_rejected_with_a_clear_error(client):
    admin = _register_org(client, "Fed Bad Config Org")
    r = client.post(CONFIGS_URL, headers=admin["headers"], json={
        "protocol": "OIDC", "provider_type": "GENERIC_OIDC", "display_name": "Incomplete",
        "configuration": {"issuer": "https://idp.example.com"},  # missing everything else
    })
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "FEDERATION_CONFIG_INVALID"


# --------------------------------------------------------------------------- #
# AC-04 — local authentication still works unchanged, federation configured or not
# --------------------------------------------------------------------------- #
def test_ac04_local_login_still_works_after_federation_is_configured(client):
    admin = _register_org(client, "Fed Coexistence Org")
    client.post(CONFIGS_URL, headers=admin["headers"], json=_oidc_payload())

    # The org owner's own local password login is completely unaffected.
    login = client.post("/api/v1/auth/login", json={"email": admin["email"], "password": OWNER_PASSWORD})
    assert login.status_code == 200, login.text
    assert login.json()["access_token"]
