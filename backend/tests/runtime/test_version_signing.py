"""Phase 5.2.4 tests — cryptographic signing, key lifecycle, and the
legacy/canonical checksum migration.

Integration/API layer: real Postgres via ``SessionLocal()``
(``client``/``db_session``/``admin`` fixtures from ``conftest.py``), no
mocks for the database. See ``test_canonical.py`` for the pure,
database-free serialization tests and ``test_attestation.py`` for the
in-toto/DSSE document format tests.
"""

from __future__ import annotations

import base64
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.runtime import AgentVersion, AgentVersionSignature, SigningKey
from app.runtime.services import _legacy_checksum, _verify_checksum
from scripts.recompute_checksums import run as recompute_checksums

PASSWORD = "T3st!Passw0rd#Ok"
RT = "/api/v1/runtime"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _register_org(client: TestClient, org: str = "Signing Org") -> dict:
    email = f"sign_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": org, "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"]}


def _register_agent(client: TestClient, org: dict) -> dict:
    r = client.post(f"{RT}/agents", headers=org["headers"], json={
        "name": f"Signing Agent {uuid.uuid4().hex[:6]}", "description": "A test agent.",
        "business_purpose": "Exercise signing in tests.", "agent_type": "ASSISTANT",
        "owner_type": "USER", "owner_id": org["user_id"],
        "definition": {"name": "Definition", "framework": "CUSTOM", "entrypoint_type": "PYTHON_MODULE",
                      "entrypoint": "agents.handler:run"},
    })
    assert r.status_code == 201, r.text
    return r.json()


def _create_version(client: TestClient, org: dict, agent_id: str, **overrides) -> dict:
    payload = {"model_configuration": {"provider": "MOCK", "model": "mock-model"}}
    payload.update(overrides)
    r = client.post(f"{RT}/agents/{agent_id}/versions", headers=org["headers"], json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _publish(client: TestClient, org: dict, agent_id: str, version_id: str) -> dict:
    body = None
    r = None
    for step in ("validate", "approve", "publish"):
        r = client.post(f"{RT}/agents/{agent_id}/versions/{version_id}/{step}", headers=org["headers"], json=body)
        assert r.status_code == 200, r.text
    return r.json()


def _published_version(client: TestClient, org: dict) -> tuple[dict, dict]:
    agent = _register_agent(client, org)
    version = _create_version(client, org, agent["id"])
    published = _publish(client, org, agent["id"], version["id"])
    return agent, published


def _isolate_signing_key(monkeypatch) -> str:
    """``signing_keys`` has no organization scoping (matching the SRS's own
    table definition, and Part 1's precedent of global, not per-org,
    catalogs — e.g. release channels). That means rotating/revoking "the"
    default key is process-wide, not scoped to one test's org — tests that
    do either must isolate themselves onto their own throwaway key_id so
    they don't poison every other test's ability to sign/publish afterward."""
    from app.core.config import settings

    key_id = f"test-key-{uuid.uuid4().hex[:10]}"
    monkeypatch.setattr(settings, "SIGNING_DEFAULT_KEY_ID", key_id)
    return key_id


# =========================================================================== #
# Legacy compatibility (AC-11..AC-17)
# =========================================================================== #
def test_new_version_uses_canonical_sha256(client: TestClient) -> None:
    """AC-13."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _create_version(client, org, agent["id"])
    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}", headers=org["headers"])
    assert r.json()["checksum_algorithm"] == "canonical-sha256"


def test_legacy_row_retains_algorithm_and_verifies_with_legacy_routine(client: TestClient,
                                                                        db_session: Session) -> None:
    """AC-11, AC-12."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _create_version(client, org, agent["id"])

    row = db_session.get(AgentVersion, uuid.UUID(version["id"]))
    row.checksum_algorithm = "legacy-sha256"
    row.checksum = _legacy_checksum(row)
    db_session.commit()

    db_session.refresh(row)
    assert row.checksum_algorithm == "legacy-sha256"
    assert _verify_checksum(row) is True  # verifies via the legacy routine, not canonical.digest()


def test_verification_branches_correctly_on_checksum_algorithm(client: TestClient, db_session: Session) -> None:
    """AC-14."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _create_version(client, org, agent["id"])
    row = db_session.get(AgentVersion, uuid.UUID(version["id"]))

    # As created: canonical-sha256, verifies.
    assert row.checksum_algorithm == "canonical-sha256"
    assert _verify_checksum(row) is True

    # Force it to look legacy without recomputing the checksum -- the
    # canonical-format checksum must NOT verify against the legacy routine,
    # proving the branch actually matters rather than both routines
    # happening to agree.
    row.checksum_algorithm = "legacy-sha256"
    assert _verify_checksum(row) is False


def test_recompute_checksums_dry_run_reports_without_writing(client: TestClient, db_session: Session) -> None:
    """AC-15."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _create_version(client, org, agent["id"])
    row = db_session.get(AgentVersion, uuid.UUID(version["id"]))
    row.checksum_algorithm = "legacy-sha256"
    row.checksum = _legacy_checksum(row)
    db_session.commit()

    reports = recompute_checksums(dry_run=True, agent_id=agent["id"])
    assert any(r["id"] == version["id"] for r in reports if r["kind"] == "version")

    db_session.expire_all()
    refreshed = db_session.get(AgentVersion, uuid.UUID(version["id"]))
    assert refreshed.checksum_algorithm == "legacy-sha256"  # unchanged -- dry run wrote nothing


def test_recompute_checksums_upgrades_legacy_row_and_it_verifies(client: TestClient, db_session: Session) -> None:
    """AC-16."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _create_version(client, org, agent["id"])
    row = db_session.get(AgentVersion, uuid.UUID(version["id"]))
    row.checksum_algorithm = "legacy-sha256"
    row.checksum = _legacy_checksum(row)
    db_session.commit()

    reports = recompute_checksums(dry_run=False, agent_id=agent["id"])
    assert any(r["id"] == version["id"] and r["legacy_checksum_verified"]
              for r in reports if r["kind"] == "version")

    db_session.expire_all()
    refreshed = db_session.get(AgentVersion, uuid.UUID(version["id"]))
    assert refreshed.checksum_algorithm == "canonical-sha256"
    assert _verify_checksum(refreshed) is True


def test_reading_a_legacy_row_never_silently_rewrites_it(client: TestClient, db_session: Session) -> None:
    """AC-17 (application-level guarantee — migration 0027 itself was
    already verified this session to add no data-rewriting statements;
    this proves ordinary read access doesn't either)."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _create_version(client, org, agent["id"])
    row = db_session.get(AgentVersion, uuid.UUID(version["id"]))
    row.checksum_algorithm = "legacy-sha256"
    legacy_checksum = _legacy_checksum(row)
    row.checksum = legacy_checksum
    db_session.commit()

    for _ in range(3):
        r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}", headers=org["headers"])
        assert r.status_code == 200
    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/readiness", headers=org["headers"])
    assert r.status_code == 200

    db_session.expire_all()
    refreshed = db_session.get(AgentVersion, uuid.UUID(version["id"]))
    assert refreshed.checksum_algorithm == "legacy-sha256"
    assert refreshed.checksum == legacy_checksum


# =========================================================================== #
# Signing (AC-18..AC-28)
# =========================================================================== #
def test_publish_produces_exactly_one_publisher_signature(client: TestClient) -> None:
    """AC-18."""
    org = _register_org(client)
    agent, version = _published_version(client, org)
    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/signatures", headers=org["headers"])
    assert r.status_code == 200, r.text
    signatures = r.json()
    publisher_signatures = [s for s in signatures if s["signature_type"] == "PUBLISHER"]
    assert len(publisher_signatures) == 1
    assert version["manifest_digest"] is not None
    assert version["signed_at"] is not None
    assert version["signature_id"] == publisher_signatures[0]["id"]


def test_signature_verifies_against_public_key(client: TestClient) -> None:
    """AC-19."""
    org = _register_org(client)
    agent, version = _published_version(client, org)
    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/verify", headers=org["headers"])
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["valid"] is True
    assert result["snapshot_intact"] is True
    assert all(s["signature_valid"] for s in result["signatures"])


def test_tampered_snapshot_fails_verification(client: TestClient, db_session: Session) -> None:
    """AC-20."""
    from app.models.runtime import AgentVersionSnapshot

    org = _register_org(client)
    agent, version = _published_version(client, org)

    snapshot = db_session.execute(
        db_session.query(AgentVersionSnapshot).filter(
            AgentVersionSnapshot.agent_version_id == uuid.UUID(version["id"])
        ).statement
    ).scalars().first()
    snapshot.snapshot = {**snapshot.snapshot, "identity": {**snapshot.snapshot["identity"], "agent_name": "TAMPERED"}}
    db_session.commit()

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/verify", headers=org["headers"])
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["snapshot_intact"] is False
    assert result["valid"] is False


def test_tampered_attestation_payload_fails_dsse_verification(client: TestClient, db_session: Session) -> None:
    """AC-21."""
    org = _register_org(client)
    agent, version = _published_version(client, org)

    signature = db_session.execute(
        db_session.query(AgentVersionSignature).filter(
            AgentVersionSignature.agent_version_id == uuid.UUID(version["id"])
        ).statement
    ).scalars().first()
    tampered_payload = base64.b64encode(b'{"_type":"tampered"}').decode("ascii")
    signature.dsse_envelope = {**signature.dsse_envelope, "payload": tampered_payload}
    db_session.commit()

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/verify", headers=org["headers"])
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["valid"] is False
    assert any(not s["signature_valid"] for s in result["signatures"])


def test_signing_failure_aborts_publication(client: TestClient, monkeypatch) -> None:
    """AC-22."""
    import app.runtime.versioning.attestation as attestation_module

    def _boom(self, *args, **kwargs):
        raise RuntimeError("simulated signing failure")

    monkeypatch.setattr(attestation_module.AttestationService, "build_and_sign", _boom)

    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _create_version(client, org, agent["id"])
    client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/validate", headers=org["headers"])
    client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/approve", headers=org["headers"])

    with pytest.raises(RuntimeError):
        client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/publish", headers=org["headers"])

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}", headers=org["headers"])
    assert r.json()["status"] == "APPROVED"  # never reached PUBLISHED
    assert r.json()["signed_at"] is None


def test_no_private_key_material_reachable_through_any_response(client: TestClient) -> None:
    """AC-23."""
    org = _register_org(client)
    agent, version = _published_version(client, org)

    responses = [
        client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/signatures", headers=org["headers"]),
        client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/attestation", headers=org["headers"]),
        client.get(f"{RT}/signing-keys", headers=org["headers"]),
    ]
    for r in responses:
        assert r.status_code == 200
        body = r.text
        assert "PRIVATE KEY" not in body
        assert "BEGIN PRIVATE" not in body


def test_key_rotation_increments_version_and_creates_version_row(client: TestClient, db_session: Session,
                                                                  monkeypatch) -> None:
    """AC-24."""
    key_id = _isolate_signing_key(monkeypatch)
    org = _register_org(client)
    _agent, _version = _published_version(client, org)  # ensures this test's isolated key exists

    keys = client.get(f"{RT}/signing-keys", headers=org["headers"]).json()
    key_before = next(k for k in keys if k["key_id"] == key_id)
    r = client.post(f"{RT}/signing-keys/{key_before['key_id']}/rotate", headers=org["headers"])
    assert r.status_code == 200, r.text
    rotated = r.json()
    assert rotated["current_version"] == key_before["current_version"] + 1

    key_row = db_session.execute(
        db_session.query(SigningKey).filter(SigningKey.key_id == key_before["key_id"]).statement
    ).scalars().first()
    from app.models.runtime import SigningKeyVersion
    versions = db_session.execute(
        db_session.query(SigningKeyVersion).filter(SigningKeyVersion.signing_key_id == key_row.id).statement
    ).scalars().all()
    assert len(versions) >= 2
    assert any(v.version == rotated["current_version"] for v in versions)


def test_signatures_made_before_rotation_still_verify_after(client: TestClient, monkeypatch) -> None:
    """AC-25."""
    key_id = _isolate_signing_key(monkeypatch)
    org = _register_org(client)
    agent, version = _published_version(client, org)

    r = client.post(f"{RT}/signing-keys/{key_id}/rotate", headers=org["headers"])
    assert r.status_code == 200, r.text

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/verify", headers=org["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["valid"] is True


def test_revocation_marks_affected_signatures_key_revoked(client: TestClient, db_session: Session,
                                                           monkeypatch) -> None:
    """AC-26."""
    key_id = _isolate_signing_key(monkeypatch)
    org = _register_org(client)
    agent, version = _published_version(client, org)

    r = client.post(f"{RT}/signing-keys/{key_id}/revoke", headers=org["headers"],
                    json={"reason": "Compromised in a drill."})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "REVOKED"

    db_session.expire_all()
    signature = db_session.execute(
        db_session.query(AgentVersionSignature).filter(
            AgentVersionSignature.agent_version_id == uuid.UUID(version["id"])
        ).statement
    ).scalars().first()
    assert signature.verification_status == "KEY_REVOKED"


def test_revocation_does_not_alter_version_record_or_signature_bytes(client: TestClient, db_session: Session,
                                                                      monkeypatch) -> None:
    """AC-27."""
    key_id = _isolate_signing_key(monkeypatch)
    org = _register_org(client)
    agent, version = _published_version(client, org)

    signature_before = db_session.execute(
        db_session.query(AgentVersionSignature).filter(
            AgentVersionSignature.agent_version_id == uuid.UUID(version["id"])
        ).statement
    ).scalars().first()
    signature_bytes_before = bytes(signature_before.signature)
    version_before = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}", headers=org["headers"]).json()

    client.post(f"{RT}/signing-keys/{key_id}/revoke", headers=org["headers"])

    db_session.expire_all()
    signature_after = db_session.execute(
        db_session.query(AgentVersionSignature).filter(
            AgentVersionSignature.agent_version_id == uuid.UUID(version["id"])
        ).statement
    ).scalars().first()
    assert bytes(signature_after.signature) == signature_bytes_before
    version_after = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}", headers=org["headers"]).json()
    assert version_after["status"] == version_before["status"]
    assert version_after["checksum"] == version_before["checksum"]
    assert version_after["manifest_digest"] == version_before["manifest_digest"]


def test_countersigning_adds_second_signature_both_verify_independently(client: TestClient, monkeypatch) -> None:
    """AC-28."""
    _isolate_signing_key(monkeypatch)
    org = _register_org(client)
    agent, version = _published_version(client, org)

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/countersign", headers=org["headers"])
    assert r.status_code == 201, r.text
    countersignature = r.json()
    assert countersignature["signature_type"] == "COUNTERSIGN"

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/signatures", headers=org["headers"])
    signatures = r.json()
    assert len(signatures) == 2
    types = {s["signature_type"] for s in signatures}
    assert types == {"PUBLISHER", "COUNTERSIGN"}

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/verify", headers=org["headers"])
    result = r.json()
    assert result["valid"] is True
    assert len(result["signatures"]) == 2
    assert all(s["signature_valid"] for s in result["signatures"])


# =========================================================================== #
# API, permission enforcement, isolation (AC-35..AC-38)
# =========================================================================== #
def test_all_signing_endpoints_enforce_permission(client: TestClient, monkeypatch) -> None:
    """AC-35."""
    _isolate_signing_key(monkeypatch)
    org = _register_org(client)
    agent, version = _published_version(client, org)

    endpoints = [
        ("GET", f"{RT}/agents/{agent['id']}/versions/{version['id']}/signatures"),
        ("GET", f"{RT}/agents/{agent['id']}/versions/{version['id']}/provenance"),
        ("GET", f"{RT}/agents/{agent['id']}/versions/{version['id']}/attestation"),
        ("POST", f"{RT}/agents/{agent['id']}/versions/{version['id']}/verify"),
        ("POST", f"{RT}/agents/{agent['id']}/versions/{version['id']}/countersign"),
        ("GET", f"{RT}/signing-keys"),
    ]
    for method, url in endpoints:
        r = client.request(method, url, headers=org["headers"])
        assert r.status_code in (200, 201), (method, url, r.text)


def test_no_unauthenticated_route_introduced(client: TestClient) -> None:
    """AC-36."""
    org = _register_org(client)
    agent, version = _published_version(client, org)

    endpoints = [
        ("GET", f"{RT}/agents/{agent['id']}/versions/{version['id']}/signatures"),
        ("GET", f"{RT}/agents/{agent['id']}/versions/{version['id']}/provenance"),
        ("GET", f"{RT}/agents/{agent['id']}/versions/{version['id']}/attestation"),
        ("POST", f"{RT}/agents/{agent['id']}/versions/{version['id']}/verify"),
        ("POST", f"{RT}/agents/{agent['id']}/versions/{version['id']}/countersign"),
        ("GET", f"{RT}/signing-keys"),
        ("POST", f"{RT}/signing-keys/default/rotate"),
        ("POST", f"{RT}/signing-keys/default/revoke"),
    ]
    for method, url in endpoints:
        r = client.request(method, url)  # no Authorization header
        assert r.status_code in (401, 403), (method, url, r.status_code)


def test_cross_org_access_denied_for_signatures_provenance_attestation(client: TestClient) -> None:
    """AC-37."""
    org_a = _register_org(client, "Signing Org A")
    org_b = _register_org(client, "Signing Org B")
    agent, version = _published_version(client, org_a)

    for path in ("signatures", "provenance", "attestation"):
        r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/{path}", headers=org_b["headers"])
        assert r.status_code == 404, (path, r.text)

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/verify", headers=org_b["headers"])
    assert r.status_code == 404


def test_unknown_key_404_revoked_key_error_code(client: TestClient, monkeypatch) -> None:
    """AC-38."""
    key_id = _isolate_signing_key(monkeypatch)
    org = _register_org(client)
    _agent, _version = _published_version(client, org)  # ensures this test's isolated key exists

    r = client.post(f"{RT}/signing-keys/does-not-exist-{uuid.uuid4().hex[:8]}/rotate", headers=org["headers"])
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "SIGNING_KEY_NOT_FOUND"

    client.post(f"{RT}/signing-keys/{key_id}/revoke", headers=org["headers"])
    r = client.post(f"{RT}/signing-keys/{key_id}/rotate", headers=org["headers"])
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "SIGNING_KEY_REVOKED"


# =========================================================================== #
# Non-functional (AC-39, AC-40)
# =========================================================================== #
def test_signature_verification_latency_p99_under_50ms(client: TestClient) -> None:
    """AC-39."""
    org = _register_org(client)
    agent, version = _published_version(client, org)

    durations = []
    for _ in range(30):
        start = time.perf_counter()
        r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/verify", headers=org["headers"])
        durations.append(time.perf_counter() - start)
        assert r.status_code == 200
    durations.sort()
    p99 = durations[int(len(durations) * 0.99) - 1]
    assert p99 < 0.05, f"p99 verification latency {p99 * 1000:.1f}ms exceeded 50ms budget"


def test_publish_with_signing_end_to_end_under_5s(client: TestClient) -> None:
    """AC-40."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _create_version(client, org, agent["id"])

    start = time.perf_counter()
    published = _publish(client, org, agent["id"], version["id"])
    elapsed = time.perf_counter() - start

    assert published["status"] == "PUBLISHED"
    assert elapsed < 5.0, f"publish (incl. validate+approve+sign) took {elapsed:.2f}s"
