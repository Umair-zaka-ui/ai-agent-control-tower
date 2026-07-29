"""Phase 5.7a.5 tests — per-organization provider credentials.

Four groups, matching the build prompt's own acceptance-criteria
groupings: storage & encryption (AC-01..05), resolution (AC-06..10),
redaction (AC-11..15), API & integrity (AC-16..30 — the suite-level ones,
AC-25..28, are proven by the full-suite run cited in the phase summary,
not duplicated here except where a specific new behavior needs its own
assertion).

Every credential value used anywhere in this file is an obviously-fake
placeholder (``sk-test-fake-...``), never a real provider key (AC-30).
"""

from __future__ import annotations

import inspect
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.identity.errors import ErrorCode, IdentityError
from app.models.rbac import AuthorizationAudit
from app.models.runtime import ProviderCredential, RuntimeEvent
from app.runtime.providers import credential_crypto
from app.runtime.providers.credential_crypto import decrypt_secret, encrypt_secret, mask_hint
from app.runtime.providers.mock import MockProvider
from app.runtime.providers.openai_compatible import OpenAICompatibleProvider
from app.runtime.services import ProviderCredentialService
from tests.runtime.conftest import load_fixture, replay_transport

PASSWORD = "T3st!Passw0rd#Ok"
RT = "/api/v1/runtime"
_FAKE_SECRET = "sk-test-fake-1234567890abcdef"


def _capturing_transport(fixture_name: str) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    body = load_fixture(fixture_name)
    sent: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=body, request=request)

    return httpx.MockTransport(_handler), sent


# --------------------------------------------------------------------------- #
# HTTP helpers (local copies, matching this directory's established
# convention of not importing fixtures across test modules)
# --------------------------------------------------------------------------- #
def _register_org(client: TestClient, org_name: str = "Credentials Org") -> dict:
    email = f"cred_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": org_name, "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"]}


def _invite_member(client: TestClient, admin: dict, *, role: str = "VIEWER") -> dict:
    email = f"credm_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/identity/users", headers=admin["headers"], json={
        "email": email, "display_name": "Member", "password": PASSWORD, "role": role,
        "organization_id": admin["organization_id"],
    })
    assert r.status_code in (200, 201), r.text
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    return {"headers": {"Authorization": f"Bearer {tokens['access_token']}"}}


def _register_agent(client: TestClient, admin: dict) -> dict:
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"Credential Agent {uuid.uuid4().hex[:6]}", "agent_type": "ASSISTANT", "criticality": "MEDIUM",
        "description": "A test agent.", "business_purpose": "Exercise per-org provider credentials in tests.",
        "owner_type": "USER", "owner_id": admin["user_id"], "technical_owner_id": admin["user_id"],
        "compliance_owner_id": admin["user_id"],
        "definition": {"name": "Definition", "framework": "CUSTOM", "entrypoint_type": "FUNCTION",
                      "entrypoint": "agents.handler:run"},
    })
    assert r.status_code == 201, r.text
    return r.json()


def _activate_agent(client: TestClient, admin: dict, agent_id: str) -> None:
    for step in ("register", "validate"):
        r = client.post(f"{RT}/agents/{agent_id}/{step}", headers=admin["headers"])
        assert r.status_code == 200, r.text
    r = client.post(f"{RT}/agents/{agent_id}/identity/create-and-associate", headers=admin["headers"], json={
        "client_id": f"agent-identity-{uuid.uuid4().hex[:10]}",
    })
    assert r.status_code == 200, r.text
    for step in ("submit-for-approval", "approve", "activate"):
        r = client.post(f"{RT}/agents/{agent_id}/{step}", headers=admin["headers"])
        assert r.status_code == 200, r.text


def _publish_version(client: TestClient, admin: dict, agent_id: str, *, model_configuration: dict) -> dict:
    r = client.post(f"{RT}/agents/{agent_id}/versions", headers=admin["headers"], json={
        "model_configuration": model_configuration,
    })
    assert r.status_code == 201, r.text
    version = r.json()
    for step in ("validate", "approve", "publish"):
        r = client.post(f"{RT}/agents/{agent_id}/versions/{version['id']}/{step}", headers=admin["headers"])
        assert r.status_code == 200, r.text
    return r.json()


def _deploy(client: TestClient, admin: dict, agent_id: str, version_id: str) -> dict:
    r = client.post(f"{RT}/deployments", headers=admin["headers"], params={"agent_id": agent_id}, json={
        "agent_version_id": version_id, "environment": "DEVELOPMENT",
    })
    assert r.status_code == 201, r.text
    deployment = r.json()
    r = client.post(f"{RT}/deployments/{deployment['id']}/deploy", headers=admin["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def _ready_agent(client: TestClient, admin: dict, *, model_configuration: dict) -> dict:
    agent = _register_agent(client, admin)
    _activate_agent(client, admin, agent["id"])
    version = _publish_version(client, admin, agent["id"], model_configuration=model_configuration)
    deployment = _deploy(client, admin, agent["id"], version["id"])
    return {"agent": agent, "version": version, "deployment": deployment}


def _run_execution(client: TestClient, admin: dict, agent_id: str, *, input_payload: dict | None = None) -> dict:
    r = client.post(f"{RT}/executions", headers=admin["headers"], json={
        "agent_id": agent_id, "input_payload": input_payload or {"question": "hello"},
    })
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture(autouse=True)
def _fresh_encryption_key(monkeypatch, tmp_path) -> None:
    """Every test in this file gets its own encryption key file, so no
    test's stored ciphertext depends on whatever key another test run (or
    a real developer's ``.keys/`` directory) happens to have."""
    monkeypatch.setattr(settings, "MODEL_CREDENTIAL_ENCRYPTION_KEY", None)
    monkeypatch.setattr(settings, "MODEL_CREDENTIAL_ENCRYPTION_KEY_PATH", str(tmp_path / "model_credentials.key"))
    credential_crypto.reset_cached_key()
    yield
    credential_crypto.reset_cached_key()


# --------------------------------------------------------------------------- #
# Storage & encryption — AC-01..05
# --------------------------------------------------------------------------- #
def test_stored_credential_is_encrypted_at_rest(db_session: Session, admin: dict) -> None:
    """AC-01."""
    ProviderCredentialService(db_session).store(
        _FakeActor(admin["user_id"]), uuid.UUID(admin["organization_id"]), "OPENAI_COMPATIBLE", _FAKE_SECRET)
    row = db_session.execute(
        select(ProviderCredential).where(ProviderCredential.organization_id == uuid.UUID(admin["organization_id"]))
    ).scalars().one()
    assert _FAKE_SECRET not in row.encrypted_secret
    assert row.encrypted_secret != _FAKE_SECRET


def test_decrypted_value_round_trips_through_resolve_secret(db_session: Session, admin: dict) -> None:
    """AC-02."""
    org_id = uuid.UUID(admin["organization_id"])
    service = ProviderCredentialService(db_session)
    service.store(_FakeActor(admin["user_id"]), org_id, "OPENAI_COMPATIBLE", _FAKE_SECRET)

    resolved = service.resolve_secret(org_id, "OPENAI_COMPATIBLE")
    assert resolved.api_key == _FAKE_SECRET

    # And the raw crypto utility itself round-trips independently of the service.
    assert decrypt_secret(encrypt_secret(_FAKE_SECRET)) == _FAKE_SECRET


def test_encryption_key_is_read_from_settings_not_hardcoded() -> None:
    """AC-03 — inspection test: the module reads ``settings.MODEL_
    CREDENTIAL_ENCRYPTION_KEY``/``_PATH``, and contains no hardcoded
    Fernet-key-shaped literal (44 base64 characters ending in ``=``)
    assigned directly as a constant."""
    import re

    source = inspect.getsource(credential_crypto)
    assert "settings.MODEL_CREDENTIAL_ENCRYPTION_KEY" in source
    assert "settings.MODEL_CREDENTIAL_ENCRYPTION_KEY_PATH" in source
    # A real Fernet key is exactly 44 base64 characters ending in '='.
    hardcoded_key_pattern = re.compile(r'["\'][A-Za-z0-9_=-]{43}=["\']')
    assert not hardcoded_key_pattern.search(source), "credential_crypto.py appears to contain a hardcoded key literal"


def test_secret_hint_exposes_at_most_last_four_characters() -> None:
    """AC-04."""
    hint = mask_hint(_FAKE_SECRET)
    assert hint == _FAKE_SECRET[-4:]
    assert len(hint) <= 4
    assert hint not in _FAKE_SECRET[:-4]  # not accidentally a longer slice


def test_credentials_are_scoped_per_organization(db_session: Session, admin: dict) -> None:
    """AC-05 — org A cannot read org B's credential (service level)."""
    org_a = uuid.UUID(admin["organization_id"])
    org_b = uuid.uuid4()
    service = ProviderCredentialService(db_session)
    service.store(_FakeActor(admin["user_id"]), org_a, "OPENAI_COMPATIBLE", _FAKE_SECRET)

    with pytest.raises(IdentityError) as exc_info:
        service.get_metadata(org_b, "OPENAI_COMPATIBLE")
    assert exc_info.value.code == ErrorCode.PROVIDER_CREDENTIAL_NOT_FOUND


class _FakeActor:
    """A minimal stand-in with just the ``.id`` attribute ``store()``/
    ``_record_event`` need — avoids constructing a full ``User`` ORM
    instance for service-level (non-HTTP) tests in this file."""

    def __init__(self, user_id: str) -> None:
        self.id = uuid.UUID(user_id)


# --------------------------------------------------------------------------- #
# Resolution — AC-06..10
# --------------------------------------------------------------------------- #
def test_stored_credential_reaches_the_outbound_request(client: TestClient, db_session: Session,
                                                         monkeypatch) -> None:
    """AC-06."""
    transport, sent = _capturing_transport("simple_completion.json")
    monkeypatch.setattr(OpenAICompatibleProvider, "_build_default_transport", lambda self: transport)

    org = _register_org(client)
    r = client.put(f"{RT}/providers/OPENAI_COMPATIBLE/credentials", headers=org["headers"],
                   json={"secret": _FAKE_SECRET})
    assert r.status_code == 200, r.text

    setup = _ready_agent(client, org, model_configuration={"provider": "OPENAI_COMPATIBLE", "model": "gpt-3.5-turbo"})
    execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["status"] == "SUCCEEDED"
    assert sent[0].headers["authorization"] == f"Bearer {_FAKE_SECRET}"


def test_resolution_order_per_org_then_fallback_then_none(db_session: Session, admin: dict) -> None:
    """AC-07."""
    org_id = uuid.UUID(admin["organization_id"])
    service = ProviderCredentialService(db_session)

    # 3. Neither configured -> None.
    assert service.resolve_secret(org_id, "OPENAI_COMPATIBLE").api_key is None

    # 2. Fallback only.
    from unittest.mock import patch
    with patch.dict(settings.MODEL_PROVIDER_API_KEYS, {"OPENAI_COMPATIBLE": "sk-test-fake-fallback"}, clear=True):
        assert service.resolve_secret(org_id, "OPENAI_COMPATIBLE").api_key == "sk-test-fake-fallback"

        # 1. Per-org beats the fallback once configured.
        service.store(_FakeActor(admin["user_id"]), org_id, "OPENAI_COMPATIBLE", _FAKE_SECRET)
        assert service.resolve_secret(org_id, "OPENAI_COMPATIBLE").api_key == _FAKE_SECRET


def test_local_provider_executes_with_no_credential_configured(client: TestClient, monkeypatch) -> None:
    """AC-08 — MOCK (no notion of a credential at all) and OPENAI_COMPATIBLE
    pointed at what a real deployment would use for an unauthenticated
    local endpoint (Ollama), both succeed with nothing configured
    anywhere."""
    org = _register_org(client)
    mock_setup = _ready_agent(client, org, model_configuration={"provider": "MOCK", "model": "mock-model"})
    mock_execution = _run_execution(client, org, mock_setup["agent"]["id"])
    assert mock_execution["status"] == "SUCCEEDED"

    transport = replay_transport("simple_completion.json")
    monkeypatch.setattr(OpenAICompatibleProvider, "_build_default_transport", lambda self: transport)
    org_b = _register_org(client, "Local Ollama Org")
    local_setup = _ready_agent(client, org_b, model_configuration={
        "provider": "OPENAI_COMPATIBLE", "model": "llama3",
    })
    local_execution = _run_execution(client, org_b, local_setup["agent"]["id"])
    assert local_execution["status"] == "SUCCEEDED"


def test_real_provider_with_no_credential_fails_with_credential_required(client: TestClient, monkeypatch) -> None:
    """AC-09."""
    transport = replay_transport("error_authentication_failed.json", status_code=401)
    monkeypatch.setattr(OpenAICompatibleProvider, "_build_default_transport", lambda self: transport)

    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={"provider": "OPENAI_COMPATIBLE", "model": "gpt-3.5-turbo"})
    execution = _run_execution(client, org, setup["agent"]["id"])

    assert execution["status"] == "FAILED"
    assert execution["error_code"] == "PROVIDER_CREDENTIAL_REQUIRED"


def test_snapshot_contains_no_credential_value(client: TestClient, db_session: Session) -> None:
    """AC-10 — resolution happens at execution time, never at snapshot
    time: a published version's frozen snapshot never contains the
    org's configured credential."""
    import json as jsonlib

    from app.models.runtime import AgentVersionSnapshot

    org = _register_org(client)
    r = client.put(f"{RT}/providers/OPENAI_COMPATIBLE/credentials", headers=org["headers"],
                   json={"secret": _FAKE_SECRET})
    assert r.status_code == 200, r.text

    setup = _ready_agent(client, org, model_configuration={"provider": "OPENAI_COMPATIBLE", "model": "gpt-3.5-turbo"})

    snapshot = db_session.execute(
        select(AgentVersionSnapshot).where(AgentVersionSnapshot.agent_version_id == uuid.UUID(setup["version"]["id"]))
    ).scalars().one()
    blob = jsonlib.dumps(snapshot.snapshot, default=str)
    assert _FAKE_SECRET not in blob


# --------------------------------------------------------------------------- #
# Redaction — AC-11..15
# --------------------------------------------------------------------------- #
def test_no_log_line_contains_the_credential_value(client: TestClient, monkeypatch, caplog) -> None:
    """AC-11."""
    transport, _ = _capturing_transport("simple_completion.json")
    monkeypatch.setattr(OpenAICompatibleProvider, "_build_default_transport", lambda self: transport)

    org = _register_org(client)
    r = client.put(f"{RT}/providers/OPENAI_COMPATIBLE/credentials", headers=org["headers"],
                   json={"secret": _FAKE_SECRET})
    assert r.status_code == 200, r.text
    setup = _ready_agent(client, org, model_configuration={"provider": "OPENAI_COMPATIBLE", "model": "gpt-3.5-turbo"})

    with caplog.at_level("DEBUG"):
        execution = _run_execution(client, org, setup["agent"]["id"])
    assert execution["status"] == "SUCCEEDED"
    assert _FAKE_SECRET not in caplog.text


def test_no_audit_event_contains_the_credential_value(client: TestClient, db_session: Session) -> None:
    """AC-12."""
    org = _register_org(client)
    r = client.put(f"{RT}/providers/OPENAI_COMPATIBLE/credentials", headers=org["headers"],
                   json={"secret": _FAKE_SECRET})
    assert r.status_code == 200, r.text
    r = client.delete(f"{RT}/providers/OPENAI_COMPATIBLE/credentials", headers=org["headers"])
    assert r.status_code == 204

    org_id = uuid.UUID(org["organization_id"])
    runtime_events = db_session.execute(
        select(RuntimeEvent).where(RuntimeEvent.organization_id == org_id)
    ).scalars().all()
    for event in runtime_events:
        assert _FAKE_SECRET not in str(event.payload)

    audit_rows = db_session.execute(
        select(AuthorizationAudit).where(AuthorizationAudit.organization_id == org_id)
    ).scalars().all()
    for row in audit_rows:
        assert _FAKE_SECRET not in str(row.meta)


def test_no_error_message_contains_the_credential_value(client: TestClient, monkeypatch) -> None:
    """AC-13 — composes with 5.7a.4's adapter-level scrubbing: a
    credential that was configured but rejected must not leak through the
    resulting error message either."""
    transport = replay_transport("error_authentication_failed.json", status_code=401)
    monkeypatch.setattr(OpenAICompatibleProvider, "_build_default_transport", lambda self: transport)

    org = _register_org(client)
    r = client.put(f"{RT}/providers/OPENAI_COMPATIBLE/credentials", headers=org["headers"],
                   json={"secret": _FAKE_SECRET})
    assert r.status_code == 200, r.text
    setup = _ready_agent(client, org, model_configuration={"provider": "OPENAI_COMPATIBLE", "model": "gpt-3.5-turbo"})
    execution = _run_execution(client, org, setup["agent"]["id"])

    assert execution["status"] == "FAILED"
    assert execution["error_code"] == "AUTHENTICATION_FAILED"
    assert _FAKE_SECRET not in (execution["error_message"] or "")


def test_credential_read_api_never_returns_the_value(client: TestClient) -> None:
    """AC-14."""
    org = _register_org(client)
    r = client.put(f"{RT}/providers/OPENAI_COMPATIBLE/credentials", headers=org["headers"],
                   json={"secret": _FAKE_SECRET})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "secret" not in body and "encrypted_secret" not in body
    assert body["secret_hint"] == _FAKE_SECRET[-4:]

    listed = client.get(f"{RT}/providers/credentials", headers=org["headers"])
    assert listed.status_code == 200, listed.text
    assert _FAKE_SECRET not in listed.text
    assert listed.json()[0]["secret_hint"] == _FAKE_SECRET[-4:]


def test_model_repr_does_not_expose_the_value(db_session: Session, admin: dict) -> None:
    """AC-15."""
    org_id = uuid.UUID(admin["organization_id"])
    ProviderCredentialService(db_session).store(_FakeActor(admin["user_id"]), org_id, "OPENAI_COMPATIBLE",
                                                _FAKE_SECRET)
    row = db_session.execute(
        select(ProviderCredential).where(ProviderCredential.organization_id == org_id)
    ).scalars().one()
    assert _FAKE_SECRET not in repr(row)
    assert row.encrypted_secret not in repr(row)


# --------------------------------------------------------------------------- #
# API & integrity — AC-16..24
# --------------------------------------------------------------------------- #
def test_put_upserts_and_a_second_put_replaces_and_re_encrypts(client: TestClient, db_session: Session) -> None:
    """AC-16."""
    org = _register_org(client)
    r1 = client.put(f"{RT}/providers/OPENAI_COMPATIBLE/credentials", headers=org["headers"],
                    json={"secret": _FAKE_SECRET})
    assert r1.status_code == 200, r1.text
    org_id = uuid.UUID(org["organization_id"])
    row_after_first = db_session.execute(
        select(ProviderCredential).where(ProviderCredential.organization_id == org_id)
    ).scalars().one()
    first_ciphertext = row_after_first.encrypted_secret
    first_id = row_after_first.id

    second_secret = "sk-test-fake-replacement-99999"
    r2 = client.put(f"{RT}/providers/OPENAI_COMPATIBLE/credentials", headers=org["headers"],
                    json={"secret": second_secret})
    assert r2.status_code == 200, r2.text
    assert r2.json()["secret_hint"] == second_secret[-4:]

    # The PUT above ran in a separate request-scoped session; this
    # fixture's own session must be told to drop its identity-map cache
    # before re-reading, or it will silently return the pre-replace row.
    db_session.expire_all()
    rows = db_session.execute(
        select(ProviderCredential).where(ProviderCredential.organization_id == org_id)
    ).scalars().all()
    assert len(rows) == 1, "a second PUT must replace, not duplicate, the row"
    assert rows[0].id == first_id
    assert rows[0].encrypted_secret != first_ciphertext
    assert decrypt_secret(rows[0].encrypted_secret) == second_secret


def test_delete_removes_and_resolution_falls_through(client: TestClient, db_session: Session) -> None:
    """AC-17."""
    org = _register_org(client)
    org_id = uuid.UUID(org["organization_id"])
    r = client.put(f"{RT}/providers/OPENAI_COMPATIBLE/credentials", headers=org["headers"],
                   json={"secret": _FAKE_SECRET})
    assert r.status_code == 200, r.text

    r = client.delete(f"{RT}/providers/OPENAI_COMPATIBLE/credentials", headers=org["headers"])
    assert r.status_code == 204

    assert db_session.execute(
        select(ProviderCredential).where(ProviderCredential.organization_id == org_id)
    ).scalars().first() is None
    resolved = ProviderCredentialService(db_session).resolve_secret(org_id, "OPENAI_COMPATIBLE")
    assert resolved.api_key is None  # falls through to "none" (no fallback configured in this test)


def test_test_endpoint_performs_a_real_classified_call_without_returning_the_credential(
    client: TestClient, monkeypatch) -> None:
    """AC-18."""
    transport = replay_transport("simple_completion.json")
    monkeypatch.setattr(OpenAICompatibleProvider, "_build_default_transport", lambda self: transport)

    org = _register_org(client)
    r = client.put(f"{RT}/providers/OPENAI_COMPATIBLE/credentials", headers=org["headers"],
                   json={"secret": _FAKE_SECRET})
    assert r.status_code == 200, r.text

    result = client.post(f"{RT}/providers/OPENAI_COMPATIBLE/credentials/test", headers=org["headers"])
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["success"] is True
    assert _FAKE_SECRET not in result.text

    failing_transport = replay_transport("error_rate_limited.json", status_code=429)
    monkeypatch.setattr(OpenAICompatibleProvider, "_build_default_transport", lambda self: failing_transport)
    failed_result = client.post(f"{RT}/providers/OPENAI_COMPATIBLE/credentials/test", headers=org["headers"])
    assert failed_result.status_code == 200, failed_result.text
    failed_body = failed_result.json()
    assert failed_body["success"] is False
    assert failed_body["error_class"] == "RATE_LIMITED"
    assert _FAKE_SECRET not in failed_result.text


def test_all_four_endpoints_enforce_their_permissions(client: TestClient) -> None:
    """AC-19 — ``VIEWER`` (this codebase's built-in read-only role) holds
    none of this platform's ``runtime.*`` permissions at all (confirmed:
    its fixed grant set is ``agent.view``/``policy.view``/``audit.view``/
    ``dashboard.view``/``agent_action.view``/``approval.view`` only — see
    ``SYSTEM_ROLE_PERMISSIONS`` in ``rbac_service.py``), so it is rejected
    from all four endpoints, including the view-only ``GET``. ``ADMIN``
    (which does hold both ``runtime.provider.view`` and ``.manage``, via
    ``_ALL``) is used as the positive control proving the endpoints work
    at all for a correctly-permissioned actor."""
    org = _register_org(client)
    viewer = _invite_member(client, org, role="VIEWER")

    assert client.get(f"{RT}/providers/credentials", headers=viewer["headers"]).status_code == 403
    assert client.put(f"{RT}/providers/OPENAI_COMPATIBLE/credentials", headers=viewer["headers"],
                      json={"secret": _FAKE_SECRET}).status_code == 403
    assert client.delete(f"{RT}/providers/OPENAI_COMPATIBLE/credentials", headers=viewer["headers"]).status_code == 403
    assert client.post(f"{RT}/providers/OPENAI_COMPATIBLE/credentials/test",
                       headers=viewer["headers"]).status_code == 403

    # No auth at all -> rejected the same way any other unauthenticated
    # call to a require_permission-gated route in this codebase is.
    assert client.get(f"{RT}/providers/credentials").status_code == 403

    # Positive control: the org owner (SUPER_ADMIN) can reach every one.
    assert client.get(f"{RT}/providers/credentials", headers=org["headers"]).status_code == 200
    assert client.put(f"{RT}/providers/OPENAI_COMPATIBLE/credentials", headers=org["headers"],
                      json={"secret": _FAKE_SECRET}).status_code == 200


def test_cross_org_credential_access_via_api_is_rejected(client: TestClient) -> None:
    """AC-20 — every endpoint scopes strictly by the authenticated actor's
    own organization_id; there is no parameter through which a caller
    could name a different organization at all."""
    org_a = _register_org(client, "Cred Org A")
    org_b = _register_org(client, "Cred Org B")
    assert client.put(f"{RT}/providers/OPENAI_COMPATIBLE/credentials", headers=org_a["headers"],
                      json={"secret": _FAKE_SECRET}).status_code == 200

    listed_b = client.get(f"{RT}/providers/credentials", headers=org_b["headers"])
    assert listed_b.status_code == 200
    assert listed_b.json() == []

    delete_b = client.delete(f"{RT}/providers/OPENAI_COMPATIBLE/credentials", headers=org_b["headers"])
    assert delete_b.status_code == 404
    assert delete_b.json()["error"]["code"] == "PROVIDER_CREDENTIAL_NOT_FOUND"

    # Org A's own credential is untouched by org B's failed attempt.
    listed_a = client.get(f"{RT}/providers/credentials", headers=org_a["headers"])
    assert len(listed_a.json()) == 1


def test_mock_provider_and_api_key_forwarding_path_unchanged() -> None:
    """AC-22 — the registry's ``model``/``api_key`` forwarding (5.7a.2) and
    ``MockProvider`` itself are untouched by this phase; the adapter needed
    no modification at all (this phase only changed *where* the key comes
    from, not how it reaches ``registry.resolve()``)."""
    accepted = inspect.signature(OpenAICompatibleProvider.__init__).parameters
    assert "api_key" in accepted and "base_url" in accepted
    assert "api_key" not in inspect.signature(MockProvider.__init__).parameters


def test_authorization_gateway_runs_before_credential_resolution(client: TestClient, monkeypatch) -> None:
    """AC-23 — an unauthorized execution request never reaches
    ``ProviderCredentialService.resolve_for_version`` at all (queueing,
    and therefore the worker, is never reached for a denied request)."""
    calls: list[str] = []
    original = ProviderCredentialService.resolve_for_version

    def _spy(self, organization_id, version):
        calls.append(str(organization_id))
        return original(self, organization_id, version)

    monkeypatch.setattr(ProviderCredentialService, "resolve_for_version", _spy)

    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={"provider": "MOCK", "model": "mock-model"})
    viewer = _invite_member(client, org, role="VIEWER")

    r = client.post(f"{RT}/executions", headers=viewer["headers"], json={
        "agent_id": setup["agent"]["id"], "input_payload": {"a": 1},
    })
    assert r.status_code == 403, r.text
    assert calls == [], "credential resolution ran despite authorization denying the request first"


def test_output_and_usage_contract_preserved(client: TestClient) -> None:
    """AC-24."""
    org = _register_org(client)
    setup = _ready_agent(client, org, model_configuration={"provider": "MOCK", "model": "mock-model"})
    execution = _run_execution(client, org, setup["agent"]["id"], input_payload={"question": "hello"})
    assert execution["status"] == "SUCCEEDED"
    assert execution["output_payload"]["echo"] == {"question": "hello"}
    assert execution["model_usage"]["provider"] == "MOCK"


# --------------------------------------------------------------------------- #
# AC-29 — no new TODO/FIXME/NotImplementedError/skip/xfail
# --------------------------------------------------------------------------- #
def test_no_new_todo_or_skip_markers_in_this_phases_files() -> None:
    """AC-29."""
    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[2]
    files = [
        backend_dir / "app" / "runtime" / "providers" / "credential_crypto.py",
        backend_dir / "app" / "runtime" / "services.py",
        backend_dir / "app" / "runtime" / "routes.py",
        backend_dir / "app" / "runtime" / "schemas.py",
        backend_dir / "app" / "models" / "runtime.py",
        backend_dir / "migrations" / "versions" / "0029_provider_credentials.py",
    ]
    forbidden = ("TODO", "FIXME", "NotImplementedError", "pytest.mark.skip", "pytest.mark.xfail")
    for path in files:
        text = path.read_text(encoding="utf-8")
        hits = [token for token in forbidden if token in text]
        assert not hits, f"{path.name} contains forbidden marker(s): {hits}"


# --------------------------------------------------------------------------- #
# AC-30 — no real credential committed as a fixture literal
# --------------------------------------------------------------------------- #
def test_no_committed_fixture_contains_a_production_shaped_key() -> None:
    """AC-30."""
    from pathlib import Path

    fixtures_dir = Path(__file__).parent / "fixtures" / "providers"
    for path in fixtures_dir.glob("*.json"):
        text = path.read_text()
        assert "sk-proj-" not in text and "sk-live-" not in text, f"{path.name} looks like it contains a real key"
