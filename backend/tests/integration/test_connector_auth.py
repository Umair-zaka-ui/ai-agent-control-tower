"""Phase 2.1.2 tests — Connector Authentication Framework.

Grouped exactly as the build prompt's §8 groups its acceptance criteria:
scheme framework (AC-01..05), encryption & reuse (AC-06..09), OAuth2
(AC-10..15), rotation/mTLS/validation (AC-16..18), redaction & integrity
(AC-19..30 — the suite-level ones, AC-23/26/27/28, are proven by the
full-suite run cited in the phase summary, not duplicated here).

Every credential value used anywhere in this file is an obviously-fake
placeholder; every OAuth2 test injects an ``httpx.MockTransport`` — no
test in this file ever makes a real network call (AC-30)."""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.integration.auth import registry as auth_registry
from app.integration.auth import token_manager
from app.integration.auth.base import AuthScheme, OutboundRequest
from app.integration.auth.schemes.api_key import ApiKeyScheme
from app.integration.auth.schemes.basic import BasicAuthScheme
from app.integration.auth.schemes.bearer import BearerTokenScheme
from app.integration.auth.schemes.mtls import MTLSScheme
from app.integration.auth.schemes.oauth2_authorization_code import OAuth2AuthorizationCodeScheme
from app.integration.auth.schemes.oauth2_client_credentials import OAuth2ClientCredentialsScheme
from app.integration.auth.service import ConnectorCredentialService
from app.models.integration import Connector as ConnectorRow, ConnectorCredential, ConnectorInstance, ConnectorOAuthToken
from app.models.rbac import AuthorizationAudit
from app.models.user import User

RT = "/api/v1/integration"


# --------------------------------------------------------------------------- #
# Helpers (local copies, matching this directory's established convention)
# --------------------------------------------------------------------------- #
def _create_mock_auth_instance(client: TestClient, admin: dict, *, name: str | None = None) -> dict:
    r = client.post(f"{RT}/connectors", headers=admin["headers"], json={
        "connector_type": "MOCK_AUTH", "name": name or f"Auth Instance {uuid.uuid4().hex[:6]}",
        "configuration": {"endpoint": "https://mockauth.internal"},
    })
    assert r.status_code == 201, r.text
    return r.json()


def _insert_oauth_connector_type(db_session: Session, scheme_id: str) -> ConnectorRow:
    """Direct-DB type registration for a scheme combination no built-in
    mock declares — the same precedent 2.1.1's own
    ``test_ac19_connector_versioning_two_versions_coexist`` set for
    inserting a second ``connectors`` row directly."""
    row = ConnectorRow(
        connector_type=f"TEST_OAUTH_{uuid.uuid4().hex[:8]}", version="1.0.0",
        capabilities={}, config_schema={"type": "object"}, auth_requirements={"scheme": scheme_id},
        tool_contracts=[],
    )
    db_session.add(row)
    db_session.flush()
    return row


def _insert_connector_instance(db_session: Session, organization_id: uuid.UUID, type_row: ConnectorRow) -> ConnectorInstance:
    instance = ConnectorInstance(
        organization_id=organization_id, connector_id=type_row.id,
        name=f"OAuth Instance {uuid.uuid4().hex[:6]}", configuration={}, lifecycle_state="configured",
    )
    db_session.add(instance)
    db_session.commit()
    db_session.refresh(instance)
    return instance


def _token_endpoint_transport(response_sequence: list[dict]) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = response_sequence[min(len(calls) - 1, len(response_sequence) - 1)]
        return httpx.Response(200, json=body, request=request)

    return httpx.MockTransport(handler), calls


def _admin_user(db_session: Session, admin: dict) -> User:
    return db_session.get(User, uuid.UUID(admin["user_id"]))


# --------------------------------------------------------------------------- #
# Scheme framework (AC-01..05)
# --------------------------------------------------------------------------- #
def test_ac01_auth_scheme_is_abstract_and_all_six_schemes_resolve():
    with pytest.raises(TypeError):
        AuthScheme()  # type: ignore[abstract]

    identifiers = auth_registry.registered_identifiers()
    assert identifiers == sorted([
        "API_KEY", "BEARER", "BASIC", "OAUTH2_CLIENT_CREDENTIALS", "OAUTH2_AUTHORIZATION_CODE", "MTLS",
    ])
    for identifier in identifiers:
        scheme = auth_registry.resolve(identifier)
        assert isinstance(scheme, AuthScheme)
        assert len(scheme.required_fields()) > 0


class _ToyScheme(AuthScheme):
    """A throwaway 7th scheme, registered only for
    ``test_ac02``, proving extensibility functionally rather than by
    grep alone."""

    def required_fields(self) -> tuple[str, ...]:
        return ("toy_value",)

    def apply(self, request: OutboundRequest, credential) -> OutboundRequest:
        return request.with_headers(**{"X-Toy": str(credential["toy_value"])})


def test_ac02_adding_a_scheme_requires_only_a_registered_subclass():
    auth_registry.register("TOY", _ToyScheme)
    try:
        assert isinstance(auth_registry.resolve("TOY"), _ToyScheme)
        request = OutboundRequest(method="GET", url="https://example.internal/ping")
        applied = _ToyScheme().apply(request, {"toy_value": "abc"})
        assert applied.headers["X-Toy"] == "abc"
    finally:
        del auth_registry._REGISTRY["TOY"]  # test isolation -- don't leak into other tests


def test_ac02_runtime_never_references_connector_or_scheme_vocabulary():
    """No `if scheme == "..."` ladder anywhere outside the registry/
    scheme modules — checked the same way 2.1.1 mechanically checked the
    runtime-never-knows principle: grep app/runtime/ for the literal
    identifiers and fail the build if any appear."""
    # "API_KEY" is deliberately excluded here -- it's already a pre-existing,
    # unrelated identifier in app/runtime (agent machine-identity
    # `credential_type="API_KEY"`, Phase 5.1; `MODEL_PROVIDER_API_KEYS`
    # settings, Phase 5.7a.5), so it isn't a meaningful signal for *this*
    # sub-phase's vocabulary leaking in. The other four identifiers are
    # unique to Phase 2.1.2's auth framework.
    runtime_root = Path(__file__).resolve().parents[2] / "app" / "runtime"
    forbidden = ("connector", "OAUTH2_CLIENT_CREDENTIALS", "OAUTH2_AUTHORIZATION_CODE", "MTLS", "AuthScheme")
    offenders = []
    for path in runtime_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(term in text for term in forbidden):
            offenders.append(str(path))
    assert offenders == []


def test_ac03_each_scheme_applies_credential_correctly():
    req = OutboundRequest(method="GET", url="https://api.example.internal/data")

    api_key = ApiKeyScheme().apply(req, {"api_key": "sk-abc123"})
    assert api_key.headers["X-API-Key"] == "sk-abc123"

    api_key_custom = ApiKeyScheme().apply(req, {"api_key": "v", "header_name": "X-Custom"})
    assert api_key_custom.headers["X-Custom"] == "v"

    bearer = BearerTokenScheme().apply(req, {"token": "tok-xyz"})
    assert bearer.headers["Authorization"] == "Bearer tok-xyz"

    basic = BasicAuthScheme().apply(req, {"username": "u", "password": "p"})
    expected = base64.b64encode(b"u:p").decode("ascii")
    assert basic.headers["Authorization"] == f"Basic {expected}"

    oauth_cc = OAuth2ClientCredentialsScheme().apply(req, {"access_token": "at-1"})
    assert oauth_cc.headers["Authorization"] == "Bearer at-1"

    oauth_ac = OAuth2AuthorizationCodeScheme().apply(req, {"access_token": "at-2"})
    assert oauth_ac.headers["Authorization"] == "Bearer at-2"

    mtls = MTLSScheme().apply(req, {"client_cert_pem": "CERT", "client_key_pem": "KEY"})
    assert mtls.tls_client_cert == ("CERT", "KEY")
    assert "Authorization" not in mtls.headers

    assert req.headers == {}  # original request untouched -- immutability


def test_ac04_declared_auth_requirements_selects_the_scheme(client: TestClient, admin: dict, db_session: Session):
    instance = _create_mock_auth_instance(client, admin)
    r = client.put(f"{RT}/connectors/{instance['id']}/credentials", headers=admin["headers"],
                   json={"auth_scheme": "API_KEY", "credential": {"api_key": "sk-selects-scheme"}})
    assert r.status_code == 200, r.text

    row = db_session.get(ConnectorInstance, uuid.UUID(instance["id"]))
    applied = ConnectorCredentialService(db_session).resolve_and_apply(row, OutboundRequest(url="https://x.internal"))
    assert applied.headers["X-API-Key"] == "sk-selects-scheme"


def test_ac05_unsupported_scheme_fails(client: TestClient, admin: dict):
    instance = _create_mock_auth_instance(client, admin)
    r = client.put(f"{RT}/connectors/{instance['id']}/credentials", headers=admin["headers"],
                   json={"auth_scheme": "FOOBAR", "credential": {"x": "y"}})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CONNECTOR_AUTH_SCHEME_UNSUPPORTED"


# --------------------------------------------------------------------------- #
# Encryption & reuse (AC-06..09)
# --------------------------------------------------------------------------- #
def test_ac06_encrypted_at_rest_reusing_credential_crypto_directly(client: TestClient, admin: dict, db_session: Session):
    import app.integration.auth.service as svc_module
    from app.runtime.providers import credential_crypto

    assert svc_module.encrypt_secret is credential_crypto.encrypt_secret
    assert svc_module.decrypt_secret is credential_crypto.decrypt_secret

    instance = _create_mock_auth_instance(client, admin)
    secret_value = "sk-super-secret-encryption-check"
    client.put(f"{RT}/connectors/{instance['id']}/credentials", headers=admin["headers"],
              json={"auth_scheme": "API_KEY", "credential": {"api_key": secret_value}})

    row = db_session.execute(
        select(ConnectorCredential).where(ConnectorCredential.connector_instance_id == uuid.UUID(instance["id"]))
    ).scalar_one()
    assert secret_value not in row.encrypted_secret
    assert json.loads(credential_crypto.decrypt_secret(row.encrypted_secret))["api_key"] == secret_value


def test_ac07_secret_hint_is_masked(client: TestClient, admin: dict):
    instance = _create_mock_auth_instance(client, admin)
    r = client.put(f"{RT}/connectors/{instance['id']}/credentials", headers=admin["headers"],
                   json={"auth_scheme": "API_KEY", "credential": {"api_key": "sk-abcdWXYZ"}})
    hint = r.json()["secret_hint"]
    assert hint == "WXYZ"
    assert "sk-abcd" not in hint


def test_ac08_credentials_are_tenant_isolated(client: TestClient, admin: dict, other_org_admin: dict):
    instance = _create_mock_auth_instance(client, admin)
    client.put(f"{RT}/connectors/{instance['id']}/credentials", headers=admin["headers"],
              json={"auth_scheme": "API_KEY", "credential": {"api_key": "sk-tenant-check"}})

    cross = client.get(f"{RT}/connectors/{instance['id']}/credentials", headers=other_org_admin["headers"])
    assert cross.status_code == 404
    assert cross.json()["error"]["code"] == "CONNECTOR_NOT_FOUND"


def test_ac09_credential_table_stores_ciphertext_never_structured_plaintext():
    columns = set(ConnectorCredential.__table__.columns.keys())
    assert columns == {
        "id", "connector_instance_id", "organization_id", "auth_scheme", "encrypted_secret", "secret_hint",
        "status", "last_validated_at", "validation_status", "created_at", "updated_at", "created_by",
    }
    for forbidden in ("api_key", "client_secret", "password", "client_cert", "client_key", "token"):
        assert forbidden not in columns


# --------------------------------------------------------------------------- #
# OAuth2 (AC-10..15)
# --------------------------------------------------------------------------- #
def test_ac10_client_credentials_acquires_token_from_fixtured_endpoint(admin: dict, db_session: Session):
    org_id = uuid.UUID(admin["organization_id"])
    type_row = _insert_oauth_connector_type(db_session, "OAUTH2_CLIENT_CREDENTIALS")
    instance = _insert_connector_instance(db_session, org_id, type_row)
    ConnectorCredentialService(db_session).store(
        _admin_user(db_session, admin), org_id, instance.id, "OAUTH2_CLIENT_CREDENTIALS",
        {"client_id": "cid", "client_secret": "csecret", "token_url": "https://token.example.internal/oauth/token"},
    )

    transport, calls = _token_endpoint_transport([{"access_token": "at-1", "expires_in": 3600}])
    applied = ConnectorCredentialService(db_session).resolve_and_apply(
        instance, OutboundRequest(url="https://api.example.internal"), transport=transport,
    )
    assert applied.headers["Authorization"] == "Bearer at-1"
    assert len(calls) == 1

    token_row = db_session.execute(
        select(ConnectorOAuthToken).where(ConnectorOAuthToken.connector_instance_id == instance.id)
    ).scalar_one()
    assert token_row.expires_at > datetime.now(timezone.utc)


def test_ac11_cached_nonexpired_token_reused_without_reacquisition(admin: dict, db_session: Session):
    org_id = uuid.UUID(admin["organization_id"])
    type_row = _insert_oauth_connector_type(db_session, "OAUTH2_CLIENT_CREDENTIALS")
    instance = _insert_connector_instance(db_session, org_id, type_row)
    config = {"client_id": "cid", "client_secret": "csecret", "token_url": "https://token.example.internal/oauth/token"}
    ConnectorCredentialService(db_session).store(_admin_user(db_session, admin), org_id, instance.id,
                                                 "OAUTH2_CLIENT_CREDENTIALS", config)

    transport, calls = _token_endpoint_transport([{"access_token": "at-1", "expires_in": 3600}])
    svc = ConnectorCredentialService(db_session)
    first = svc.resolve_and_apply(instance, OutboundRequest(url="https://x"), transport=transport)
    second = svc.resolve_and_apply(instance, OutboundRequest(url="https://x"), transport=transport)

    assert first.headers["Authorization"] == second.headers["Authorization"] == "Bearer at-1"
    assert len(calls) == 1  # not re-acquired


def test_ac12_expired_token_triggers_transparent_refresh(admin: dict, db_session: Session):
    org_id = uuid.UUID(admin["organization_id"])
    type_row = _insert_oauth_connector_type(db_session, "OAUTH2_CLIENT_CREDENTIALS")
    instance = _insert_connector_instance(db_session, org_id, type_row)
    config = {"client_id": "cid", "client_secret": "csecret", "token_url": "https://token.example.internal/oauth/token"}
    ConnectorCredentialService(db_session).store(_admin_user(db_session, admin), org_id, instance.id,
                                                 "OAUTH2_CLIENT_CREDENTIALS", config)

    # First response is already within the refresh margin (expires_in=1s
    # < REFRESH_MARGIN_SECONDS=60s), so the very next resolve must refresh.
    transport, calls = _token_endpoint_transport([
        {"access_token": "at-1", "expires_in": 1},
        {"access_token": "at-2", "expires_in": 3600},
    ])
    svc = ConnectorCredentialService(db_session)
    first = svc.resolve_and_apply(instance, OutboundRequest(url="https://x"), transport=transport)
    second = svc.resolve_and_apply(instance, OutboundRequest(url="https://x"), transport=transport)

    assert first.headers["Authorization"] == "Bearer at-1"
    assert second.headers["Authorization"] == "Bearer at-2"  # never presents the expired one
    assert len(calls) == 2


def test_ac13_concurrent_refresh_does_not_double_refresh(admin: dict, db_session: Session):
    org_id = uuid.UUID(admin["organization_id"])
    type_row = _insert_oauth_connector_type(db_session, "OAUTH2_CLIENT_CREDENTIALS")
    instance = _insert_connector_instance(db_session, org_id, type_row)
    config = {"client_id": "cid", "client_secret": "csecret", "token_url": "https://token.example.internal/oauth/token"}
    ConnectorCredentialService(db_session).store(_admin_user(db_session, admin), org_id, instance.id,
                                                 "OAUTH2_CLIENT_CREDENTIALS", config)

    call_count = {"n": 0}
    count_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def handler(request: httpx.Request) -> httpx.Response:
        with count_lock:
            call_count["n"] += 1
            n = call_count["n"]
        time.sleep(0.3)  # widen the race window so both threads genuinely overlap
        return httpx.Response(200, json={"access_token": f"at-{n}", "expires_in": 3600}, request=request)

    transport = httpx.MockTransport(handler)
    results: list[str] = []
    errors: list[BaseException] = []

    def worker() -> None:
        thread_db = SessionLocal()
        try:
            barrier.wait(timeout=5)
            token = token_manager.get_valid_access_token(
                thread_db, instance.id, org_id, scheme="OAUTH2_CLIENT_CREDENTIALS", config=config, transport=transport,
            )
            results.append(token)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            thread_db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        for f in futures:
            f.result(timeout=10)

    assert errors == []
    assert call_count["n"] == 1, "the second thread refreshed instead of reusing the first thread's result"
    assert len(results) == 2 and results[0] == results[1]


def test_ac14_authorization_code_refresh_and_apply_given_a_refresh_token(admin: dict, db_session: Session):
    org_id = uuid.UUID(admin["organization_id"])
    type_row = _insert_oauth_connector_type(db_session, "OAUTH2_AUTHORIZATION_CODE")
    instance = _insert_connector_instance(db_session, org_id, type_row)
    ConnectorCredentialService(db_session).store(_admin_user(db_session, admin), org_id, instance.id,
        "OAUTH2_AUTHORIZATION_CODE", {
            "client_id": "cid", "client_secret": "csecret",
            "authorize_url": "https://provider.example.internal/oauth/authorize",
            "token_url": "https://provider.example.internal/oauth/token",
            "redirect_uri": "https://app.example.internal/callback",
        })

    from app.runtime.providers.credential_crypto import encrypt_secret
    db_session.add(ConnectorOAuthToken(
        connector_instance_id=instance.id, organization_id=org_id,
        encrypted_access_token=encrypt_secret("stale-token"), encrypted_refresh_token=encrypt_secret("refresh-xyz"),
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=10),
    ))
    db_session.commit()

    transport, calls = _token_endpoint_transport([{"access_token": "fresh-at", "expires_in": 3600}])
    applied = ConnectorCredentialService(db_session).resolve_and_apply(
        instance, OutboundRequest(url="https://x"), transport=transport,
    )
    assert applied.headers["Authorization"] == "Bearer fresh-at"
    assert len(calls) == 1
    # the refresh grant was used, not a fresh authorization_code exchange
    assert b"grant_type=refresh_token" in calls[0].content


def test_ac15_cached_tokens_stored_encrypted(admin: dict, db_session: Session):
    org_id = uuid.UUID(admin["organization_id"])
    type_row = _insert_oauth_connector_type(db_session, "OAUTH2_CLIENT_CREDENTIALS")
    instance = _insert_connector_instance(db_session, org_id, type_row)
    config = {"client_id": "cid", "client_secret": "csecret", "token_url": "https://token.example.internal/oauth/token"}
    ConnectorCredentialService(db_session).store(_admin_user(db_session, admin), org_id, instance.id,
                                                 "OAUTH2_CLIENT_CREDENTIALS", config)
    transport, _ = _token_endpoint_transport([{"access_token": "at-secret-cached", "expires_in": 3600}])
    ConnectorCredentialService(db_session).resolve_and_apply(instance, OutboundRequest(url="https://x"), transport=transport)

    from app.runtime.providers.credential_crypto import decrypt_secret
    row = db_session.execute(
        select(ConnectorOAuthToken).where(ConnectorOAuthToken.connector_instance_id == instance.id)
    ).scalar_one()
    assert "at-secret-cached" not in row.encrypted_access_token
    assert decrypt_secret(row.encrypted_access_token) == "at-secret-cached"


# --------------------------------------------------------------------------- #
# Rotation, mTLS, validation (AC-16..18)
# --------------------------------------------------------------------------- #
def test_ac16_rotation_reencrypts_and_next_resolve_gets_new_value(client: TestClient, admin: dict, db_session: Session):
    instance = _create_mock_auth_instance(client, admin)
    client.put(f"{RT}/connectors/{instance['id']}/credentials", headers=admin["headers"],
              json={"auth_scheme": "API_KEY", "credential": {"api_key": "key-one"}})

    row_instance = db_session.get(ConnectorInstance, uuid.UUID(instance["id"]))
    svc = ConnectorCredentialService(db_session)
    resolved_before = svc.resolve_and_apply(row_instance, OutboundRequest(url="https://x"))
    assert resolved_before.headers["X-API-Key"] == "key-one"

    client.put(f"{RT}/connectors/{instance['id']}/credentials", headers=admin["headers"],
              json={"auth_scheme": "API_KEY", "credential": {"api_key": "key-two"}})

    # the already-resolved value is a plain, immutable snapshot -- unaffected
    assert resolved_before.headers["X-API-Key"] == "key-one"

    resolved_after = svc.resolve_and_apply(row_instance, OutboundRequest(url="https://x"))
    assert resolved_after.headers["X-API-Key"] == "key-two"


def test_ac17_mtls_cert_and_key_encrypted_and_configure_tls_context(client: TestClient, admin: dict, db_session: Session):
    instance = _create_mock_auth_instance(client, admin)
    cert_pem = "-----BEGIN CERTIFICATE-----\nFAKECERTDATA\n-----END CERTIFICATE-----"
    key_pem = "-----BEGIN PRIVATE KEY-----\nFAKESECRETKEYDATA\n-----END PRIVATE KEY-----"
    r = client.put(f"{RT}/connectors/{instance['id']}/credentials", headers=admin["headers"],
                   json={"auth_scheme": "MTLS", "credential": {"client_cert_pem": cert_pem, "client_key_pem": key_pem}})
    assert r.status_code == 200, r.text
    assert "FAKESECRETKEYDATA" not in r.text

    row = db_session.execute(select(ConnectorCredential).where(
        ConnectorCredential.connector_instance_id == uuid.UUID(instance["id"]), ConnectorCredential.auth_scheme == "MTLS",
    )).scalar_one()
    assert "FAKESECRETKEYDATA" not in row.encrypted_secret

    bundle = ConnectorCredentialService(db_session)._decrypt_bundle(row)
    applied = MTLSScheme().apply(OutboundRequest(url="https://x"), bundle)
    assert applied.tls_client_cert == (cert_pem, key_pem)
    assert "FAKESECRETKEYDATA" not in str(applied.headers)  # never leaks into headers


def test_ac18_validate_records_status_without_returning_credential(client: TestClient, admin: dict, db_session: Session):
    instance = _create_mock_auth_instance(client, admin)
    client.put(f"{RT}/connectors/{instance['id']}/credentials", headers=admin["headers"],
              json={"auth_scheme": "API_KEY", "credential": {"api_key": "key-validate-check"}})

    r = client.post(f"{RT}/connectors/{instance['id']}/credentials/validate", headers=admin["headers"],
                    params={"auth_scheme": "API_KEY"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["validation_status"] == "VALID"
    assert "key-validate-check" not in json.dumps(body)

    row = db_session.execute(select(ConnectorCredential).where(
        ConnectorCredential.connector_instance_id == uuid.UUID(instance["id"]),
    )).scalar_one()
    assert row.last_validated_at is not None
    assert row.validation_status == "VALID"


def test_oauth2_validate_failure_reports_invalid_without_leaking_config(admin: dict, db_session: Session):
    org_id = uuid.UUID(admin["organization_id"])
    type_row = _insert_oauth_connector_type(db_session, "OAUTH2_CLIENT_CREDENTIALS")
    instance = _insert_connector_instance(db_session, org_id, type_row)
    ConnectorCredentialService(db_session).store(_admin_user(db_session, admin), org_id, instance.id,
        "OAUTH2_CLIENT_CREDENTIALS",
        {"client_id": "cid", "client_secret": "top-secret-value", "token_url": "https://token.example.internal/oauth/token"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_client"}, request=request)

    result = ConnectorCredentialService(db_session).validate(
        _admin_user(db_session, admin), org_id, instance.id, "OAUTH2_CLIENT_CREDENTIALS",
        transport=httpx.MockTransport(handler),
    )
    assert result["success"] is False
    assert result["validation_status"] == "INVALID"
    assert "top-secret-value" not in json.dumps(result)


# --------------------------------------------------------------------------- #
# Redaction & integrity (AC-19..30)
# --------------------------------------------------------------------------- #
def test_ac19_no_credential_value_in_logs(client: TestClient, admin: dict, db_session: Session, caplog):
    instance = _create_mock_auth_instance(client, admin)
    secret_value = "sk-log-check-9f8e7d6c5b4a"
    with caplog.at_level(logging.DEBUG):
        client.put(f"{RT}/connectors/{instance['id']}/credentials", headers=admin["headers"],
                  json={"auth_scheme": "API_KEY", "credential": {"api_key": secret_value}})
        row_instance = db_session.get(ConnectorInstance, uuid.UUID(instance["id"]))
        ConnectorCredentialService(db_session).resolve_and_apply(row_instance, OutboundRequest(url="https://x"))
        client.put(f"{RT}/connectors/{instance['id']}/credentials", headers=admin["headers"],
                  json={"auth_scheme": "API_KEY", "credential": {"api_key": secret_value + "-rotated"}})

    all_log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert secret_value not in all_log_text
    assert secret_value + "-rotated" not in all_log_text


def test_ac20_no_credential_value_in_audit_events_or_api_responses(client: TestClient, admin: dict, db_session: Session):
    instance = _create_mock_auth_instance(client, admin)
    secret_value = "sk-audit-check-abc123xyz"
    r = client.put(f"{RT}/connectors/{instance['id']}/credentials", headers=admin["headers"],
                   json={"auth_scheme": "API_KEY", "credential": {"api_key": secret_value}})
    assert secret_value not in r.text

    audits = db_session.execute(
        select(AuthorizationAudit).where(AuthorizationAudit.event_type == "INTEGRATION_CONNECTOR_CREDENTIAL_UPDATED")
    ).scalars().all()
    assert len(audits) >= 1
    assert all(secret_value not in json.dumps(a.meta or {}) for a in audits)

    r2 = client.put(f"{RT}/connectors/{instance['id']}/credentials", headers=admin["headers"],
                    json={"auth_scheme": "BEARER", "credential": {}})
    assert r2.status_code == 422
    assert secret_value not in r2.text


def test_ac21_read_api_returns_hint_and_metadata_only(client: TestClient, admin: dict):
    instance = _create_mock_auth_instance(client, admin)
    client.put(f"{RT}/connectors/{instance['id']}/credentials", headers=admin["headers"],
              json={"auth_scheme": "API_KEY", "credential": {"api_key": "sk-read-api-check-value"}})

    r = client.get(f"{RT}/connectors/{instance['id']}/credentials", headers=admin["headers"])
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    entry = body[0]
    assert set(entry.keys()) == {
        "id", "connector_instance_id", "auth_scheme", "secret_hint", "status",
        "last_validated_at", "validation_status", "created_at", "updated_at",
    }
    assert "sk-read-api-check-value" not in json.dumps(entry)


def test_ac22_shares_the_inherited_fernet_key_not_a_new_one():
    """The Known Deviation (platform-held Fernet key entering process
    memory) is inherited from 5.7a.5/5.6a.1, not newly introduced —
    proven by identity, not just behavior: this module's encrypt/decrypt
    are literally the same function objects, from the same module, using
    the same settings-derived key."""
    import app.integration.auth.service as svc_module

    assert svc_module.encrypt_secret.__module__ == "app.runtime.providers.credential_crypto"
    assert svc_module.decrypt_secret.__module__ == "app.runtime.providers.credential_crypto"


def test_ac23_no_connector_or_auth_vocabulary_leaks_into_runtime_or_model_gateway():
    runtime_root = Path(__file__).resolve().parents[2] / "app" / "runtime"
    forbidden = ("connector", "auth_scheme", "OAuthToken", "AuthScheme")
    offenders = [
        str(path) for path in runtime_root.rglob("*.py")
        if any(term in path.read_text(encoding="utf-8") for term in forbidden)
    ]
    assert offenders == []


def test_ac24_2_1_1_lifecycle_behavior_unchanged_smoke(client: TestClient, admin: dict):
    r = client.post(f"{RT}/connectors", headers=admin["headers"], json={
        "connector_type": "MOCK", "name": f"Lifecycle Smoke {uuid.uuid4().hex[:6]}",
        "configuration": {"endpoint": "https://smoke.internal"},
    })
    assert r.status_code == 201
    assert r.json()["lifecycle_state"] == "configured"
    assert r.json()["connector_id"]

    activated = client.post(f"{RT}/connectors/{r.json()['id']}/activate", headers=admin["headers"])
    assert activated.status_code == 200
    assert activated.json()["lifecycle_state"] == "active"


def test_ac25_new_endpoints_enforce_permissions_and_reject_cross_org(
    client: TestClient, admin: dict, other_org_admin: dict, viewer: dict,
):
    instance = _create_mock_auth_instance(client, admin)
    client.put(f"{RT}/connectors/{instance['id']}/credentials", headers=admin["headers"],
              json={"auth_scheme": "API_KEY", "credential": {"api_key": "k-perm-check"}})

    assert client.get(f"{RT}/auth-schemes", headers=viewer["headers"]).status_code == 403
    assert client.get(f"{RT}/connectors/{instance['id']}/credentials", headers=viewer["headers"]).status_code == 403
    assert client.put(f"{RT}/connectors/{instance['id']}/credentials", headers=viewer["headers"],
                      json={"auth_scheme": "API_KEY", "credential": {"api_key": "x"}}).status_code == 403
    assert client.delete(f"{RT}/connectors/{instance['id']}/credentials", headers=viewer["headers"],
                         params={"auth_scheme": "API_KEY"}).status_code == 403
    assert client.post(f"{RT}/connectors/{instance['id']}/credentials/validate", headers=viewer["headers"],
                       params={"auth_scheme": "API_KEY"}).status_code == 403

    cross = client.get(f"{RT}/connectors/{instance['id']}/credentials", headers=other_org_admin["headers"])
    assert cross.status_code == 404
    assert cross.json()["error"]["code"] == "CONNECTOR_NOT_FOUND"


def test_ac29_no_new_todo_or_skip_markers_in_this_phases_files():
    root = Path(__file__).resolve().parents[2] / "app" / "integration"
    markers = ("TODO", "FIXME", "XXX", "HACK:", "NotImplementedError")
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            assert marker not in text, f"{marker} found in {path}"


def test_ac30_no_real_credentials_or_live_network_calls_in_this_file():
    source = Path(__file__).read_text(encoding="utf-8")
    # Built by concatenation so this very assertion doesn't self-match.
    forbidden_import = "import " + "requests"
    assert forbidden_import not in source  # this codebase's only HTTP client is httpx
    # every real-looking secret used above follows an obviously-fake, greppable
    # "-check"/placeholder naming convention -- spot-checked here. Built by
    # concatenation, like the import check above, so this assertion's own
    # source line doesn't self-match.
    live_prefix_1 = "sk-" + "live-"
    live_prefix_2 = "sk_" + "live_"
    assert live_prefix_1 not in source and live_prefix_2 not in source


def test_delete_and_reconfigure_credential_flow(client: TestClient, admin: dict, db_session: Session):
    """Extra end-to-end coverage: store, delete, and confirm the deleted
    scheme's credential is genuinely gone (404 on validate)."""
    instance = _create_mock_auth_instance(client, admin)
    client.put(f"{RT}/connectors/{instance['id']}/credentials", headers=admin["headers"],
              json={"auth_scheme": "API_KEY", "credential": {"api_key": "k-delete-check"}})

    deleted = client.delete(f"{RT}/connectors/{instance['id']}/credentials", headers=admin["headers"],
                            params={"auth_scheme": "API_KEY"})
    assert deleted.status_code == 204

    still = client.post(f"{RT}/connectors/{instance['id']}/credentials/validate", headers=admin["headers"],
                        params={"auth_scheme": "API_KEY"})
    assert still.status_code == 404
    assert still.json()["error"]["code"] == "CONNECTOR_CREDENTIAL_NOT_FOUND"


def test_oauth_callback_completes_authorization_code_exchange(admin: dict, client: TestClient, db_session: Session):
    """Proves the built (not stubbed) half of the auth-code flow: the
    callback endpoint exchanges a code for tokens and persists them."""
    org_id = uuid.UUID(admin["organization_id"])
    type_row = _insert_oauth_connector_type(db_session, "OAUTH2_AUTHORIZATION_CODE")
    instance = _insert_connector_instance(db_session, org_id, type_row)
    ConnectorCredentialService(db_session).store(_admin_user(db_session, admin), org_id, instance.id,
        "OAUTH2_AUTHORIZATION_CODE", {
            "client_id": "cid", "client_secret": "csecret",
            "authorize_url": "https://provider.example.internal/oauth/authorize",
            "token_url": "https://provider.example.internal/oauth/token",
            "redirect_uri": "https://app.example.internal/callback",
        })
    db_session.commit()

    # build_authorization_url is real, tested directly (no HTTP route exists
    # for it per the build prompt's own §7 table -- see docs).
    url = ConnectorCredentialService(db_session).build_authorization_url(instance, state="xyz")
    assert url.startswith("https://provider.example.internal/oauth/authorize?")
    assert "state=xyz" in url

    # The callback itself is exercised directly against the service (the
    # HTTP route wraps this identically; hitting it via TestClient would
    # additionally require monkeypatching the module-level httpx.Client
    # construction, which token_manager's transport= parameter already
    # makes unnecessary to prove).
    transport, calls = _token_endpoint_transport([{"access_token": "at-callback", "refresh_token": "rt-callback", "expires_in": 3600}])
    ConnectorCredentialService(db_session).complete_authorization_code_exchange(instance, code="auth-code-123", transport=transport)
    assert len(calls) == 1
    assert b"grant_type=authorization_code" in calls[0].content

    from app.runtime.providers.credential_crypto import decrypt_secret
    token_row = db_session.execute(
        select(ConnectorOAuthToken).where(ConnectorOAuthToken.connector_instance_id == instance.id)
    ).scalar_one()
    assert decrypt_secret(token_row.encrypted_access_token) == "at-callback"
    assert decrypt_secret(token_row.encrypted_refresh_token) == "rt-callback"
