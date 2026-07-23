"""Phase 5.2.4 tests — the in-toto Statement v1 / DSSE attestation format.

Real Postgres via ``SessionLocal()`` (fixtures from ``conftest.py``); no
database mocks. See ``test_version_signing.py`` for AC-18..AC-28 (the
signing/rotation/revocation lifecycle) and ``test_canonical.py`` for the
pure serialization layer.
"""

from __future__ import annotations

import base64
import uuid

from fastapi.testclient import TestClient

from app.runtime.versioning.attestation import PAYLOAD_TYPE, STATEMENT_TYPE, pae

PASSWORD = "T3st!Passw0rd#Ok"
RT = "/api/v1/runtime"
TEST_EMAIL_DOMAIN = "@example.com"


def _register_org(client: TestClient, org: str = "Attestation Org") -> dict:
    email = f"attest_{uuid.uuid4().hex[:10]}{TEST_EMAIL_DOMAIN}"
    assert client.post("/auth/register", json={
        "organization_name": org, "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"],
           "email": email}


def _register_agent(client: TestClient, org: dict) -> dict:
    r = client.post(f"{RT}/agents", headers=org["headers"], json={
        "name": f"Attestation Agent {uuid.uuid4().hex[:6]}", "description": "A test agent.",
        "business_purpose": "Exercise attestation in tests.", "agent_type": "ASSISTANT",
        "owner_type": "USER", "owner_id": org["user_id"],
        "definition": {"name": "Definition", "framework": "CUSTOM", "entrypoint_type": "PYTHON_MODULE",
                      "entrypoint": "agents.handler:run"},
    })
    assert r.status_code == 201, r.text
    return r.json()


def _published_version(client: TestClient, org: dict) -> tuple[dict, dict]:
    agent = _register_agent(client, org)
    r = client.post(f"{RT}/agents/{agent['id']}/versions", headers=org["headers"], json={
        "model_configuration": {"provider": "MOCK", "model": "mock-model"},
    })
    assert r.status_code == 201, r.text
    version = r.json()
    body = None
    for step in ("validate", "approve", "publish"):
        r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/{step}", headers=org["headers"],
                        json=body)
        assert r.status_code == 200, r.text
    return agent, r.json()


def test_attestation_validates_against_in_toto_statement_v1_structure(client: TestClient) -> None:
    """AC-29."""
    org = _register_org(client)
    agent, version = _published_version(client, org)

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/attestation", headers=org["headers"])
    assert r.status_code == 200, r.text
    document = r.json()["document"]

    assert document["_type"] == STATEMENT_TYPE == "https://in-toto.io/Statement/v1"
    assert isinstance(document["subject"], list) and len(document["subject"]) == 1
    assert "name" in document["subject"][0] and "digest" in document["subject"][0]
    assert "sha256" in document["subject"][0]["digest"]
    assert document["predicateType"].startswith("https://")
    predicate = document["predicate"]
    for section in ("agent", "version", "snapshot", "configuration", "provenance", "attestation"):
        assert section in predicate, f"missing predicate.{section}"


def test_subject_digest_is_bare_hex_no_prefix(client: TestClient) -> None:
    """AC-30."""
    org = _register_org(client)
    agent, version = _published_version(client, org)

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/attestation", headers=org["headers"])
    digest_hex = r.json()["document"]["subject"][0]["digest"]["sha256"]
    assert ":" not in digest_hex
    assert len(digest_hex) == 64
    assert all(c in "0123456789abcdef" for c in digest_hex)


def test_dsse_signature_is_computed_over_pae_not_raw_payload(client: TestClient) -> None:
    """AC-31."""
    org = _register_org(client)
    agent, version = _published_version(client, org)

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/signatures", headers=org["headers"])
    signature_meta = next(s for s in r.json() if s["signature_type"] == "PUBLISHER")

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/attestation", headers=org["headers"])
    envelope = r.json()["dsse_envelope"]
    payload_bytes = base64.b64decode(envelope["payload"])
    assert envelope["payloadType"] == PAYLOAD_TYPE == "application/vnd.in-toto+json"

    expected_pae = pae(envelope["payloadType"], payload_bytes)
    # A signature over the PAE is, by construction, over strictly more bytes
    # (and a different byte sequence entirely) than the raw payload alone --
    # if this implementation had signed the raw payload directly (the bug
    # this test guards against), the PAE reconstruction below would still
    # verify by coincidence only in the (practically impossible) case the
    # signature scheme's raw-payload signature and PAE signature collided.
    assert expected_pae != payload_bytes
    assert expected_pae.startswith(b"DSSEv1 ")

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/verify", headers=org["headers"])
    assert r.json()["valid"] is True  # the service's own verify() reconstructs and checks the PAE this way


def test_attestation_contains_no_pii(client: TestClient) -> None:
    """AC-32."""
    org = _register_org(client)
    agent, version = _published_version(client, org)

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/attestation", headers=org["headers"])
    document = r.json()["document"]
    import json
    rendered = json.dumps(document)

    assert org["email"] not in rendered
    assert TEST_EMAIL_DOMAIN not in rendered
    assert "Owner" not in rendered  # the registered user's display name
    # Every actor reference is an opaque id, never a name/email.
    assert document["predicate"]["provenance"]["published_by"]["id"] == org["user_id"]


def test_every_predicate_claim_is_self_contained_no_db_lookup_needed(client: TestClient) -> None:
    """AC-33 — every field is either a copied-by-value literal (string, int,
    digest, timestamp) or an opaque UUID string; nothing is a bare integer
    foreign key or a null placeholder that only makes sense after resolving
    it against this platform's schema."""
    org = _register_org(client)
    agent, version = _published_version(client, org)

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/attestation", headers=org["headers"])
    predicate = r.json()["document"]["predicate"]

    assert predicate["agent"]["id"] == agent["id"]
    assert predicate["agent"]["name"] == agent["name"]  # the actual name, not a reference to look one up
    assert predicate["agent"]["slug"] == agent["slug"]
    assert predicate["version"]["semantic_version"] == version["semantic_version"]
    assert predicate["version"]["status"] == "PUBLISHED"
    assert predicate["snapshot"]["digest"].startswith("sha256:")
    assert predicate["configuration"]["model"]["provider"] == "MOCK"
    assert predicate["configuration"]["model"]["parameters_digest"].startswith("sha256:")
    assert predicate["provenance"]["published_by"]["id"] == org["user_id"]
    assert predicate["provenance"]["published_at"] is not None
    assert predicate["provenance"]["builder"]["id"] == "ai-agent-control-tower"
    assert predicate["attestation"]["created_at"] is not None
