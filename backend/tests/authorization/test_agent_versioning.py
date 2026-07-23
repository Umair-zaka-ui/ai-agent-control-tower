"""Phase 5.2 Part 1 integration tests — Enterprise Immutable Agent Versioning
& Release Management foundation: semantic version rules, the snapshot
builder, lineage, release channels, release metadata/artifacts/notes, the
version status-history ledger, and the new ``retire`` terminal state.

Complements ``test_runtime.py`` (which already covers the DRAFT -> ...
-> PUBLISHED -> DEPRECATED/REVOKED happy path and checksum tamper
detection) — everything here is new ground Phase 5.0 never exercised.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

PASSWORD = "T3st!Passw0rd#Ok"
RT = "/api/v1/runtime"


def _register_org(client: TestClient, org: str = "Versioning Org") -> dict:
    email = f"ver_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": org, "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"],
            "organization_id": me["user"]["organization_id"], "email": email}


def _register_agent(client: TestClient, admin: dict) -> dict:
    r = client.post(f"{RT}/agents", headers=admin["headers"], json={
        "name": f"Versioned Agent {uuid.uuid4().hex[:6]}", "description": "A test agent.",
        "business_purpose": "Exercise versioning in tests.", "agent_type": "ASSISTANT",
        "owner_type": "USER", "owner_id": admin["user_id"],
        "definition": {"name": "Definition", "framework": "CUSTOM", "entrypoint_type": "PYTHON_MODULE",
                      "entrypoint": "agents.handler:run"},
    })
    assert r.status_code == 201, r.text
    return r.json()


def _create_version(client: TestClient, admin: dict, agent_id: str, **overrides) -> dict:
    payload = {"model_configuration": {"provider": "MOCK", "model": "mock-model"}}
    payload.update(overrides)
    r = client.post(f"{RT}/agents/{agent_id}/versions", headers=admin["headers"], json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _advance(client: TestClient, admin: dict, agent_id: str, version_id: str, *steps: str) -> dict:
    body = None
    for step in steps:
        r = client.post(f"{RT}/agents/{agent_id}/versions/{version_id}/{step}", headers=admin["headers"],
                        json=body)
        assert r.status_code == 200, r.text
    return r.json()


def _published_version(client: TestClient, admin: dict, agent_id: str, **overrides) -> dict:
    version = _create_version(client, admin, agent_id, **overrides)
    return _advance(client, admin, agent_id, version["id"], "validate", "approve", "publish")


def _activate_agent(client: TestClient, admin: dict, agent_id: str) -> dict:
    """Phase 5.1 §20 full registry lifecycle: DRAFT -> ... -> ACTIVE — needed
    for the readiness check's ``registry_active`` condition."""
    for step in ("register", "validate"):
        r = client.post(f"{RT}/agents/{agent_id}/{step}", headers=admin["headers"])
        assert r.status_code == 200, r.text
    r = client.post(f"{RT}/agents/{agent_id}/identity/create-and-associate", headers=admin["headers"], json={
        "client_id": f"identity-{uuid.uuid4().hex[:10]}",
    })
    assert r.status_code == 200, r.text
    for step in ("submit-for-approval", "approve", "activate"):
        r = client.post(f"{RT}/agents/{agent_id}/{step}", headers=admin["headers"])
        assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# Semantic versioning rules (§15-16)
# --------------------------------------------------------------------------- #
def test_semantic_version_auto_derives_and_increments(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)

    v1 = _create_version(client, org, agent["id"])
    assert v1["semantic_version"] == "0.1.0"
    v2 = _create_version(client, org, agent["id"])
    assert v2["semantic_version"] == "0.1.1"
    v3 = _create_version(client, org, agent["id"])
    assert v3["semantic_version"] == "0.1.2"


def test_semantic_version_rejects_invalid_format(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)
    r = client.post(f"{RT}/agents/{agent['id']}/versions", headers=org["headers"], json={
        "model_configuration": {"provider": "MOCK", "model": "mock-model"},
        "semantic_version": "not-a-version",
    })
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "AGENT_VERSION_INVALID_SEMVER"


def test_semantic_version_rejects_duplicate(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)
    _create_version(client, org, agent["id"], semantic_version="1.0.0")
    r = client.post(f"{RT}/agents/{agent['id']}/versions", headers=org["headers"], json={
        "model_configuration": {"provider": "MOCK", "model": "mock-model"}, "semantic_version": "1.0.0",
    })
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "AGENT_VERSION_SEMVER_NOT_INCREASING"


def test_semantic_version_rejects_decrease(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)
    _create_version(client, org, agent["id"], semantic_version="2.0.0")
    r = client.post(f"{RT}/agents/{agent['id']}/versions", headers=org["headers"], json={
        "model_configuration": {"provider": "MOCK", "model": "mock-model"}, "semantic_version": "1.5.0",
    })
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "AGENT_VERSION_SEMVER_NOT_INCREASING"


# --------------------------------------------------------------------------- #
# Release channels (§9, §26)
# --------------------------------------------------------------------------- #
def test_release_channels_catalog_is_seeded(client: TestClient) -> None:
    org = _register_org(client)
    r = client.get(f"{RT}/release-channels", headers=org["headers"])
    assert r.status_code == 200, r.text
    names = {c["name"] for c in r.json()}
    assert {"STABLE", "BETA", "CANARY", "INTERNAL"} <= names


def test_version_defaults_to_stable_channel_and_can_override(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)
    default_version = _create_version(client, org, agent["id"])
    assert default_version["release_channel_id"] is not None

    beta_version = _create_version(client, org, agent["id"], release_channel="BETA")
    assert beta_version["release_channel_id"] != default_version["release_channel_id"]


# --------------------------------------------------------------------------- #
# Snapshot builder (§10-14)
# --------------------------------------------------------------------------- #
def test_snapshot_is_built_only_at_publish(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _create_version(client, org, agent["id"])

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/snapshot", headers=org["headers"])
    assert r.status_code == 200 and r.json() is None  # not built yet — still DRAFT

    published = _advance(client, org, agent["id"], version["id"], "validate", "approve", "publish")
    assert published["snapshot_reference"] is not None

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/snapshot", headers=org["headers"])
    assert r.status_code == 200
    snapshot = r.json()
    assert snapshot is not None
    assert len(snapshot["checksum"]) == 64
    assert snapshot["snapshot"]["identity"]["agent_id"] == agent["id"]
    assert snapshot["snapshot"]["release"]["semantic_version"] == published["semantic_version"]


# --------------------------------------------------------------------------- #
# Status history (§19, §25)
# --------------------------------------------------------------------------- #
def test_status_history_records_every_transition(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _published_version(client, org, agent["id"])
    client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/deprecate", headers=org["headers"])

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/status-history", headers=org["headers"])
    assert r.status_code == 200, r.text
    transitions = [(h["previous_status"], h["new_status"]) for h in r.json()]
    for expected in [(None, "DRAFT"), ("DRAFT", "READY_FOR_REVIEW"), ("READY_FOR_REVIEW", "APPROVED"),
                    ("APPROVED", "PUBLISHED"), ("PUBLISHED", "DEPRECATED")]:
        assert expected in transitions, (expected, transitions)


# --------------------------------------------------------------------------- #
# Retire (§24-25) and the revoke/retire terminal-state boundary
# --------------------------------------------------------------------------- #
def test_retire_requires_deprecated(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _create_version(client, org, agent["id"])
    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/retire", headers=org["headers"])
    assert r.status_code == 409, r.text  # still DRAFT


def test_retire_from_deprecated_succeeds_and_is_terminal(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _published_version(client, org, agent["id"])
    client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/deprecate", headers=org["headers"])

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/retire", headers=org["headers"])
    assert r.status_code == 200, r.text
    retired = r.json()
    assert retired["status"] == "RETIRED"
    assert retired["retired_at"] is not None

    # Terminal: cannot retire again, cannot revoke a retired version.
    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/retire", headers=org["headers"])
    assert r.status_code == 409
    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/revoke", headers=org["headers"], json={})
    assert r.status_code == 409


def test_revoke_accepts_a_reason(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _published_version(client, org, agent["id"])
    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/revoke", headers=org["headers"],
                    json={"reason": "Critical security issue found in dependency."})
    assert r.status_code == 200, r.text
    assert r.json()["revoked_reason"] == "Critical security issue found in dependency."


# --------------------------------------------------------------------------- #
# Lineage (§17-18)
# --------------------------------------------------------------------------- #
def test_lineage_links_parent_and_marks_superseded(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)

    v1 = _published_version(client, org, agent["id"])
    r = client.post(f"{RT}/agents/{agent['id']}/versions", headers=org["headers"], json={
        "model_configuration": {"provider": "MOCK", "model": "mock-model"},
    })
    v2_draft = r.json()
    assert v2_draft["parent_version_id"] == v1["id"]

    client.post(f"{RT}/agents/{agent['id']}/versions/{v1['id']}/deprecate", headers=org["headers"])
    v2 = _advance(client, org, agent["id"], v2_draft["id"], "validate", "approve", "publish")
    assert v2["parent_version_id"] == v1["id"]

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{v1['id']}", headers=org["headers"])
    assert r.json()["superseded_by_id"] == v2["id"]


def test_rollback_target_must_be_published_or_deprecated(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)
    published = _published_version(client, org, agent["id"])
    draft = _create_version(client, org, agent["id"])

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{draft['id']}/rollback-target", headers=org["headers"],
                    json={"target_version_id": published["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["rollback_target_id"] == published["id"]

    # A DRAFT version is not a valid rollback target.
    other_draft = _create_version(client, org, agent["id"])
    r = client.post(f"{RT}/agents/{agent['id']}/versions/{other_draft['id']}/rollback-target",
                    headers=org["headers"], json={"target_version_id": draft["id"]})
    assert r.status_code == 422, r.text

    # Cannot target itself.
    r = client.post(f"{RT}/agents/{agent['id']}/versions/{draft['id']}/rollback-target", headers=org["headers"],
                    json={"target_version_id": draft["id"]})
    assert r.status_code == 422, r.text


# --------------------------------------------------------------------------- #
# Release metadata / artifacts / notes (§26-28) + immutability lock (§14, §21)
# --------------------------------------------------------------------------- #
def test_release_metadata_artifacts_and_notes_editable_before_publish(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _create_version(client, org, agent["id"])

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/release-metadata",
                    headers=org["headers"], json={
                        "release_name": "Claims Q3 Refresh", "change_category": "MINOR",
                        "business_justification": "Improve denial resubmission accuracy.",
                    })
    assert r.status_code == 200, r.text
    assert r.json()["release_name"] == "Claims Q3 Refresh"

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/artifacts", headers=org["headers"],
                    json={"artifact_type": "GIT_COMMIT_SHA", "reference": "a1b2c3d"})
    assert r.status_code == 201, r.text

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/notes", headers=org["headers"],
                    json={"category": "FIXED", "note": "Fixed a denial-code mapping bug."})
    assert r.status_code == 201, r.text

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/artifacts", headers=org["headers"])
    assert len(r.json()) == 1
    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/notes", headers=org["headers"])
    assert len(r.json()) == 1


def test_release_details_are_locked_after_publish(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _published_version(client, org, agent["id"])

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/artifacts", headers=org["headers"],
                    json={"artifact_type": "GIT_COMMIT_SHA", "reference": "deadbeef"})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "AGENT_VERSION_SNAPSHOT_LOCKED"

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/notes", headers=org["headers"],
                    json={"category": "FIXED", "note": "Too late."})
    assert r.status_code == 409, r.text

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/release-metadata",
                    headers=org["headers"], json={"release_name": "Renamed after the fact"})
    assert r.status_code == 409, r.text


def test_published_snapshot_captures_release_details_attached_before_publish(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _create_version(client, org, agent["id"])

    client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/artifacts", headers=org["headers"],
               json={"artifact_type": "OCI_IMAGE_DIGEST", "reference": "sha256:abc123"})
    client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/notes", headers=org["headers"],
               json={"category": "ADDED", "note": "Initial release."})

    _advance(client, org, agent["id"], version["id"], "validate", "approve", "publish")

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/snapshot", headers=org["headers"])
    document = r.json()["snapshot"]
    assert document["release"]["artifacts"] == [{"artifact_type": "OCI_IMAGE_DIGEST", "reference": "sha256:abc123"}]
    assert document["release"]["notes"] == [{"category": "ADDED", "note": "Initial release."}]


# --------------------------------------------------------------------------- #
# Version comparison (§3)
# --------------------------------------------------------------------------- #
def test_compare_versions_reports_scalar_and_configuration_changes(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)
    v1 = _create_version(client, org, agent["id"], model_configuration={"provider": "MOCK", "model": "mock-model"})
    v2 = _create_version(client, org, agent["id"], model_configuration={"provider": "MOCK", "model": "mock-model-2"})

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{v1['id']}/compare/{v2['id']}", headers=org["headers"])
    assert r.status_code == 200, r.text
    diff = r.json()
    assert diff["identical"] is False
    assert diff["scalar_changes"]["semantic_version"] == {"from": v1["semantic_version"], "to": v2["semantic_version"]}
    assert diff["configuration_changes"]["model_configuration"]["changed"]["model"] == {
        "from": "mock-model", "to": "mock-model-2",
    }


def test_compare_versions_reports_artifact_and_note_differences(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)
    v1 = _create_version(client, org, agent["id"])
    v2 = _create_version(client, org, agent["id"])
    client.post(f"{RT}/agents/{agent['id']}/versions/{v2['id']}/artifacts", headers=org["headers"],
               json={"artifact_type": "GIT_COMMIT_SHA", "reference": "deadbeef"})

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{v1['id']}/compare/{v2['id']}", headers=org["headers"])
    assert r.status_code == 200, r.text
    diff = r.json()
    assert diff["artifacts_added"] == [{"artifact_type": "GIT_COMMIT_SHA", "reference": "deadbeef"}]
    assert diff["artifacts_removed"] == []


def test_compare_identical_versions_reports_no_changes(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)
    v1 = _create_version(client, org, agent["id"])

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{v1['id']}/compare/{v1['id']}", headers=org["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["identical"] is True
    assert body["scalar_changes"] == {}


def test_compare_versions_rejects_a_version_from_another_agent(client: TestClient) -> None:
    org = _register_org(client)
    agent_a = _register_agent(client, org)
    agent_b = _register_agent(client, org)
    v_a = _create_version(client, org, agent_a["id"])
    v_b = _create_version(client, org, agent_b["id"])

    # The URL scopes both lookups to agent_a, so a version belonging to
    # agent_b simply isn't found under it (tenant/agent-scoping, not a
    # dedicated validation error).
    r = client.get(f"{RT}/agents/{agent_a['id']}/versions/{v_a['id']}/compare/{v_b['id']}", headers=org["headers"])
    assert r.status_code == 404, r.text


# --------------------------------------------------------------------------- #
# Promotion readiness (§3, §30)
# --------------------------------------------------------------------------- #
def test_readiness_fails_when_agent_not_active(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)  # stays DRAFT — never taken through the registry lifecycle
    version = _create_version(client, org, agent["id"])

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/readiness", headers=org["headers"])
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["ready"] is False
    registry_check = next(c for c in result["checks"] if c["name"] == "registry_active")
    assert registry_check["passed"] is False


def test_readiness_flags_missing_metadata_and_artifacts(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _create_version(client, org, agent["id"])

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/readiness", headers=org["headers"])
    checks = {c["name"]: c["passed"] for c in r.json()["checks"]}
    assert checks["metadata_complete"] is False
    assert checks["artifacts_present"] is False
    assert checks["approval_prerequisites_satisfied"] is False


def test_readiness_compatibility_check_is_informational_before_analysis(client: TestClient) -> None:
    """Phase 5.2.6 superseded the Part 1 stub (this check used to always
    report ``skipped: true`` with "deferred to Part 3"). Compatibility is
    now only actually computed at publish time (see
    ``test_version_compatibility.py``), so a still-DRAFT version — never
    analyzed — reports informationally rather than failing, and is never
    ``skipped`` again."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _create_version(client, org, agent["id"])

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/readiness", headers=org["headers"])
    compat = next(c for c in r.json()["checks"] if c["name"] == "compatibility_analysis")
    assert compat["skipped"] is False
    assert compat["passed"] is True  # not yet analyzed, informational only — never blocks readiness


def test_readiness_all_checks_pass_for_a_fully_prepared_active_agent(client: TestClient) -> None:
    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _create_version(client, org, agent["id"])
    client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/artifacts", headers=org["headers"],
               json={"artifact_type": "GIT_COMMIT_SHA", "reference": "abc123"})
    client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/release-metadata", headers=org["headers"],
               json={"release_name": "Initial release", "change_category": "MINOR"})
    published = _advance(client, org, agent["id"], version["id"], "validate", "approve", "publish")
    _activate_agent(client, org, agent["id"])

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{published['id']}/readiness", headers=org["headers"])
    assert r.status_code == 200, r.text
    result = r.json()
    checks = {c["name"]: c["passed"] for c in result["checks"]}
    assert checks == {
        "snapshot_creation": True, "validation_passed": True, "metadata_complete": True,
        "owners_assigned": True, "registry_active": True, "no_blocking_governance_findings": True,
        "artifacts_present": True, "compatibility_analysis": True, "approval_prerequisites_satisfied": True,
    }
    assert result["ready"] is True


# --------------------------------------------------------------------------- #
# Tenant isolation
# --------------------------------------------------------------------------- #
def test_cross_tenant_version_snapshot_lookup_denied(client: TestClient) -> None:
    org_a = _register_org(client, "Org A")
    org_b = _register_org(client, "Org B")
    agent = _register_agent(client, org_a)
    version = _published_version(client, org_a, agent["id"])

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/snapshot", headers=org_b["headers"])
    assert r.status_code == 404
