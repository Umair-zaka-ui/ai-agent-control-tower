"""Phase 5.2.6 tests — Compatibility & Breaking-Change Detection.

Two layers, per the acceptance criteria:

- **Unit** — the pure classification functions in ``compatibility.py``,
  exercised directly with plain dicts/lists. No database, no fixtures.
- **Integration/API** — real Postgres via ``SessionLocal()``
  (``db_session``/``client``/``admin`` fixtures from ``conftest.py``), no
  mocks for the database.

Each test cites the acceptance-criterion ID it proves in its own docstring
or a trailing comment, matching the AC-01..AC-42 list in the build prompt.
"""

from __future__ import annotations

import time
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.runtime import AgentDefinition, AgentVersion
from app.runtime.versioning.compatibility import (
    CompatibilityAnalysisService,
    classify_change,
    compare_capabilities,
    compare_input_contract,
    compare_model_configuration,
    compare_output_contract,
    compare_policy,
    compare_prompt_and_metadata,
    compare_tool_bindings,
)

PASSWORD = "T3st!Passw0rd#Ok"
RT = "/api/v1/runtime"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _register_org(client: TestClient, org: str = "Compat Org") -> dict:
    email = f"compat_{uuid.uuid4().hex[:10]}@example.com"
    assert client.post("/auth/register", json={
        "organization_name": org, "name": "Owner", "email": email, "password": PASSWORD,
    }).status_code == 201
    tokens = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).json()
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=h).json()
    return {"headers": h, "user_id": me["user"]["id"], "organization_id": me["user"]["organization_id"]}


def _register_agent(client: TestClient, org: dict, *, input_schema: dict | None = None,
                    output_schema: dict | None = None) -> dict:
    definition = {"name": "Definition", "framework": "CUSTOM", "entrypoint_type": "PYTHON_MODULE",
                 "entrypoint": "agents.handler:run"}
    if input_schema is not None:
        definition["input_schema"] = input_schema
    if output_schema is not None:
        definition["output_schema"] = output_schema
    r = client.post(f"{RT}/agents", headers=org["headers"], json={
        "name": f"Compat Agent {uuid.uuid4().hex[:6]}", "description": "A test agent.",
        "business_purpose": "Exercise compatibility detection in tests.", "agent_type": "ASSISTANT",
        "owner_type": "USER", "owner_id": org["user_id"], "definition": definition,
    })
    assert r.status_code == 201, r.text
    return r.json()


def _add_definition(db_session: Session, agent_id: str, *, input_schema: dict | None = None,
                    output_schema: dict | None = None) -> str:
    """Direct DB insert — there is no REST endpoint to attach a second
    ``AgentDefinition`` to an already-registered agent, but the data model
    (and ``AgentVersionCreate.definition_id``) already supports it."""
    definition = AgentDefinition(
        agent_id=uuid.UUID(agent_id), name="Definition v2", framework="CUSTOM",
        entrypoint_type="PYTHON_MODULE", entrypoint="agents.handler:run",
        input_schema=input_schema, output_schema=output_schema,
    )
    db_session.add(definition)
    db_session.commit()
    db_session.refresh(definition)
    return str(definition.id)


def _create_version(client: TestClient, org: dict, agent_id: str, **overrides) -> dict:
    payload = {"model_configuration": {"provider": "MOCK", "model": "mock-model"}}
    payload.update(overrides)
    r = client.post(f"{RT}/agents/{agent_id}/versions", headers=org["headers"], json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _advance(client: TestClient, org: dict, agent_id: str, version_id: str, *steps: str) -> dict:
    body = None
    for step in steps:
        r = client.post(f"{RT}/agents/{agent_id}/versions/{version_id}/{step}", headers=org["headers"], json=body)
        assert r.status_code == 200, r.text
    return r.json()


def _publish(client: TestClient, org: dict, agent_id: str, version_id: str) -> dict:
    return _advance(client, org, agent_id, version_id, "validate", "approve", "publish")


# =========================================================================== #
# Unit — pure classification, no database (AC-01..AC-16, AC-41)
# =========================================================================== #
def test_input_field_removed_is_breaking() -> None:
    """AC-01."""
    baseline = {"properties": {"customer_id": {"type": "string"}}, "required": ["customer_id"]}
    candidate = {"properties": {}, "required": []}
    match = next(f for f in compare_input_contract(baseline, candidate) if f.path == "inputs.customer_id")
    assert match.category == "INPUT_CONTRACT"
    assert match.change_type == "REMOVED"
    assert match.materiality == "BREAKING"
    assert "fail validation" in match.description


def test_input_type_narrowed_is_breaking() -> None:
    """AC-02."""
    baseline = {"properties": {"amount": {"type": "string"}}}
    candidate = {"properties": {"amount": {"type": "integer"}}}
    match = next(f for f in compare_input_contract(baseline, candidate) if f.path == "inputs.amount.type")
    assert match.materiality == "BREAKING"


def test_required_input_added_with_no_default_is_breaking() -> None:
    """AC-03."""
    baseline = {"properties": {}, "required": []}
    candidate = {"properties": {"new_field": {"type": "string"}}, "required": ["new_field"]}
    match = next(f for f in compare_input_contract(baseline, candidate) if f.path == "inputs.new_field")
    assert match.change_type == "ADDED"
    assert match.materiality == "BREAKING"


def test_output_field_removed_is_breaking() -> None:
    """AC-04."""
    baseline = {"properties": {"total": {"type": "number"}}}
    candidate = {"properties": {}}
    match = next(f for f in compare_output_contract(baseline, candidate) if f.path == "outputs.total")
    assert match.category == "OUTPUT_CONTRACT"
    assert match.change_type == "REMOVED"
    assert match.materiality == "BREAKING"


def test_tool_binding_removed_is_breaking() -> None:
    """AC-05."""
    match = next(f for f in compare_tool_bindings(["tool-a", "tool-b"], ["tool-a"]) if "tool-b" in f.path)
    assert match.category == "TOOL_BINDING"
    assert match.change_type == "REMOVED"
    assert match.materiality == "BREAKING"


def test_capability_removed_is_breaking() -> None:
    """AC-06."""
    match = next(f for f in compare_capabilities(["cap-a", "cap-b"], ["cap-a"]) if "cap-b" in f.path)
    assert match.category == "CAPABILITY"
    assert match.change_type == "REMOVED"
    assert match.materiality == "BREAKING"


def test_model_provider_changed_is_breaking() -> None:
    """AC-07."""
    findings = compare_model_configuration({"provider": "MOCK", "model": "mock-model"},
                                           {"provider": "ANTHROPIC", "model": "mock-model"})
    match = next(f for f in findings if f.path == "model_configuration.provider")
    assert match.category == "MODEL_CONFIG"
    assert match.materiality == "BREAKING"


def test_resource_limit_reduced_is_breaking() -> None:
    """AC-08."""
    findings = compare_model_configuration({"provider": "MOCK", "max_output_tokens": 500},
                                           {"provider": "MOCK", "max_output_tokens": 100})
    match = next(f for f in findings if f.path == "model_configuration.max_output_tokens")
    assert match.category == "RESOURCE_LIMIT"
    assert match.materiality == "BREAKING"


def test_policy_tightened_is_breaking() -> None:
    """AC-09."""
    findings = compare_policy({"prohibited_environments": []}, {"prohibited_environments": ["PRODUCTION"]})
    match = next(f for f in findings if "PRODUCTION" in f.path)
    assert match.category == "POLICY"
    assert match.change_type == "ADDED"
    assert match.materiality == "BREAKING"


def test_optional_input_added_with_default_is_backward_compatible() -> None:
    """AC-10."""
    baseline = {"properties": {}, "required": []}
    candidate = {"properties": {"locale": {"type": "string", "default": "en-US"}}, "required": ["locale"]}
    match = next(f for f in compare_input_contract(baseline, candidate) if f.path == "inputs.locale")
    assert match.change_type == "ADDED"
    assert match.materiality == "BACKWARD_COMPATIBLE"


def test_input_type_widened_is_backward_compatible() -> None:
    """AC-11."""
    baseline = {"properties": {"count": {"type": "integer"}}}
    candidate = {"properties": {"count": {"type": "number"}}}
    match = next(f for f in compare_input_contract(baseline, candidate) if f.path == "inputs.count.type")
    assert match.materiality == "BACKWARD_COMPATIBLE"


def test_output_field_tool_and_capability_added_are_backward_compatible() -> None:
    """AC-12."""
    output_match = next(f for f in compare_output_contract({"properties": {}},
                                                            {"properties": {"trace_id": {"type": "string"}}})
                        if f.path == "outputs.trace_id")
    assert output_match.change_type == "ADDED" and output_match.materiality == "BACKWARD_COMPATIBLE"

    tool_match = next(f for f in compare_tool_bindings(["tool-a"], ["tool-a", "tool-b"]) if "tool-b" in f.path)
    assert tool_match.materiality == "BACKWARD_COMPATIBLE"

    cap_match = next(f for f in compare_capabilities(["cap-a"], ["cap-a", "cap-b"]) if "cap-b" in f.path)
    assert cap_match.materiality == "BACKWARD_COMPATIBLE"


def test_resource_limit_increased_is_backward_compatible() -> None:
    """AC-13."""
    findings = compare_model_configuration({"provider": "MOCK", "max_output_tokens": 100},
                                           {"provider": "MOCK", "max_output_tokens": 500})
    match = next(f for f in findings if f.path == "model_configuration.max_output_tokens")
    assert match.materiality == "BACKWARD_COMPATIBLE"


def test_prompt_release_notes_and_metadata_changes_are_compatible() -> None:
    """AC-14."""
    findings = compare_prompt_and_metadata({"system": "old"}, {"system": "new"}, "old notes", "new notes")
    assert findings
    assert all(f.materiality == "COMPATIBLE" for f in findings)
    assert {f.category for f in findings} == {"PROMPT", "METADATA"}


def test_sampling_parameter_change_is_compatible_provider_change_is_breaking() -> None:
    """AC-15."""
    sampling = compare_model_configuration({"provider": "MOCK", "temperature": 0.2},
                                           {"provider": "MOCK", "temperature": 0.9})
    assert next(f for f in sampling if f.path == "model_configuration.temperature").materiality == "COMPATIBLE"

    provider = compare_model_configuration({"provider": "MOCK"}, {"provider": "ANTHROPIC"})
    assert next(f for f in provider if f.path == "model_configuration.provider").materiality == "BREAKING"


def test_one_breaking_finding_among_many_compatible_yields_overall_breaking() -> None:
    """AC-16 — §4.2 precedence."""
    level, findings = classify_change(
        baseline_model_configuration={"provider": "MOCK", "temperature": 0.2},
        candidate_model_configuration={"provider": "ANTHROPIC", "temperature": 0.9},
        baseline_prompt={"system": "old"}, candidate_prompt={"system": "new"},
        baseline_release_notes="old", candidate_release_notes="new",
    )
    materialities = {f.materiality for f in findings}
    assert "BREAKING" in materialities
    assert "COMPATIBLE" in materialities
    assert level == "BREAKING"


def test_finding_descriptions_state_consequence_not_just_mechanics() -> None:
    """AC-32."""
    findings = compare_input_contract(
        {"properties": {"customer_id": {"type": "string"}}, "required": ["customer_id"]},
        {"properties": {}, "required": []},
    )
    match = next(f for f in findings if f.path == "inputs.customer_id")
    assert "fail validation" in match.description  # states the consequence, not just "field removed"


# =========================================================================== #
# Integration — real Postgres via SessionLocal(), no mocks (AC-17..AC-30,
# AC-35..AC-37, AC-42)
# =========================================================================== #
def test_baseline_unknown_when_none_resolvable(client: TestClient, db_session: Session) -> None:
    """AC-17."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _create_version(client, org, agent["id"])

    report = CompatibilityAnalysisService(db_session).analyze(uuid.UUID(version["id"]),
                                                               agent_id=uuid.UUID(agent["id"]))
    assert report["compatibility_level"] == "UNKNOWN"
    assert report["baseline_version_id"] is None
    assert any(f["category"] == "METADATA" for f in report["findings"])


def test_baseline_resolves_to_parent_when_present(client: TestClient, db_session: Session) -> None:
    """AC-18."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    v1 = _create_version(client, org, agent["id"])
    v2 = _create_version(client, org, agent["id"])
    assert v2["parent_version_id"] == v1["id"]

    report = CompatibilityAnalysisService(db_session).analyze(uuid.UUID(v2["id"]), agent_id=uuid.UUID(agent["id"]))
    assert str(report["baseline_version_id"]) == v1["id"]


def test_baseline_falls_back_to_highest_published_when_parent_is_null(client: TestClient,
                                                                       db_session: Session) -> None:
    """AC-19."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    v1 = _create_version(client, org, agent["id"])
    _publish(client, org, agent["id"], v1["id"])
    v2 = _create_version(client, org, agent["id"])
    _publish(client, org, agent["id"], v2["id"])
    v3 = _create_version(client, org, agent["id"])

    row = db_session.get(AgentVersion, uuid.UUID(v3["id"]))
    row.parent_version_id = None
    db_session.commit()

    report = CompatibilityAnalysisService(db_session).analyze(uuid.UUID(v3["id"]), agent_id=uuid.UUID(agent["id"]))
    assert str(report["baseline_version_id"]) == v2["id"]  # highest PUBLISHED older than v3, not v1


def test_explicit_baseline_override_is_honored(client: TestClient, db_session: Session) -> None:
    """AC-20."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    v1 = _create_version(client, org, agent["id"])
    _create_version(client, org, agent["id"])
    v3 = _create_version(client, org, agent["id"])  # natural parent is v2, not v1

    report = CompatibilityAnalysisService(db_session).analyze(
        uuid.UUID(v3["id"]), agent_id=uuid.UUID(agent["id"]), baseline_id=uuid.UUID(v1["id"]))
    assert str(report["baseline_version_id"]) == v1["id"]


def test_analysis_persists_compatibility_fields_and_findings(client: TestClient, db_session: Session) -> None:
    """AC-21, AC-22."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    v1 = _create_version(client, org, agent["id"], model_configuration={"provider": "MOCK", "model": "m1"})
    v2 = _create_version(client, org, agent["id"], model_configuration={"provider": "ANTHROPIC", "model": "m1"})

    service = CompatibilityAnalysisService(db_session)
    report = service.analyze(uuid.UUID(v2["id"]), agent_id=uuid.UUID(agent["id"]))
    assert report["compatibility_level"] == "BREAKING"

    row = db_session.get(AgentVersion, uuid.UUID(v2["id"]))
    assert row.compatibility_level == "BREAKING"
    assert row.compatibility_baseline_id == uuid.UUID(v1["id"])
    assert row.compatibility_analyzed_at is not None

    findings = service.list_findings(uuid.UUID(v2["id"]))
    assert any(f.category == "MODEL_CONFIG" and f.change_type == "MODIFIED" and f.materiality == "BREAKING"
              for f in findings)


def test_rerunning_analysis_replaces_findings_not_duplicates(client: TestClient, db_session: Session) -> None:
    """AC-23."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    _create_version(client, org, agent["id"])
    v2 = _create_version(client, org, agent["id"], model_configuration={"provider": "ANTHROPIC", "model": "mock-model"})

    service = CompatibilityAnalysisService(db_session)
    service.analyze(uuid.UUID(v2["id"]), agent_id=uuid.UUID(agent["id"]))
    first_count = len(service.list_findings(uuid.UUID(v2["id"])))
    service.analyze(uuid.UUID(v2["id"]), agent_id=uuid.UUID(agent["id"]))
    second_count = len(service.list_findings(uuid.UUID(v2["id"])))
    assert first_count > 0
    assert first_count == second_count


def test_semver_consistent_when_major_bump_matches_breaking(client: TestClient, db_session: Session) -> None:
    """AC-24."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    _create_version(client, org, agent["id"], semantic_version="1.0.0",
                    model_configuration={"provider": "MOCK", "model": "mock-model"})
    v2 = _create_version(client, org, agent["id"], semantic_version="2.0.0",
                         model_configuration={"provider": "ANTHROPIC", "model": "mock-model"})

    report = CompatibilityAnalysisService(db_session).analyze(uuid.UUID(v2["id"]), agent_id=uuid.UUID(agent["id"]))
    assert report["compatibility_level"] == "BREAKING"
    assert report["declared_increment"] == "major"
    assert report["expected_increment"] == "major"
    assert report["semver_consistent"] is True


def test_semver_inconsistent_when_minor_bump_used_for_breaking(client: TestClient, db_session: Session) -> None:
    """AC-25."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    _create_version(client, org, agent["id"], semantic_version="1.0.0",
                    model_configuration={"provider": "MOCK", "model": "mock-model"})
    v2 = _create_version(client, org, agent["id"], semantic_version="1.1.0",
                         model_configuration={"provider": "ANTHROPIC", "model": "mock-model"})

    report = CompatibilityAnalysisService(db_session).analyze(uuid.UUID(v2["id"]), agent_id=uuid.UUID(agent["id"]))
    assert report["compatibility_level"] == "BREAKING"
    assert report["declared_increment"] == "minor"
    assert report["expected_increment"] == "major"
    assert report["semver_consistent"] is False


def test_semver_inconsistency_does_not_block_publish(client: TestClient) -> None:
    """AC-26 — publish() never gates on compatibility/semver consistency."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    _create_version(client, org, agent["id"], semantic_version="1.0.0")
    v2 = _create_version(client, org, agent["id"], semantic_version="1.0.1",
                         model_configuration={"provider": "ANTHROPIC", "model": "mock-model"})

    published = _publish(client, org, agent["id"], v2["id"])
    assert published["status"] == "PUBLISHED"
    assert published["compatibility_level"] == "BREAKING"  # analyzed automatically, but did not block


def test_readiness_compatibility_check_is_never_skipped_and_reflects_state(client: TestClient) -> None:
    """AC-27, AC-28, AC-29."""
    org = _register_org(client)
    agent = _register_agent(client, org)

    # Never analyzed yet (still DRAFT) -- informational, never skipped.
    v1 = _create_version(client, org, agent["id"])
    r = client.get(f"{RT}/agents/{agent['id']}/versions/{v1['id']}/readiness", headers=org["headers"])
    check = next(c for c in r.json()["checks"] if c["name"] == "compatibility_analysis")
    assert check["skipped"] is False
    assert check["passed"] is True

    # BREAKING with a correctly-major-bumped candidate -- warns, does not fail.
    v2 = _create_version(client, org, agent["id"], semantic_version="2.0.0",
                         model_configuration={"provider": "ANTHROPIC", "model": "mock-model"})
    _publish(client, org, agent["id"], v2["id"])
    r = client.get(f"{RT}/agents/{agent['id']}/versions/{v2['id']}/readiness", headers=org["headers"])
    check = next(c for c in r.json()["checks"] if c["name"] == "compatibility_analysis")
    assert check["skipped"] is False
    assert check["passed"] is True
    assert "BREAKING" in check["message"]

    # BREAKING with only a patch bump -- fails (still doesn't block anything).
    v3 = _create_version(client, org, agent["id"], semantic_version="2.0.1",
                         model_configuration={"provider": "MOCK", "model": "different-model"})
    _publish(client, org, agent["id"], v3["id"])
    r = client.get(f"{RT}/agents/{agent['id']}/versions/{v3['id']}/readiness", headers=org["headers"])
    check = next(c for c in r.json()["checks"] if c["name"] == "compatibility_analysis")
    assert check["skipped"] is False
    assert check["passed"] is False


def test_publish_survives_analyzer_exception(client: TestClient, monkeypatch) -> None:
    """AC-30."""
    import app.runtime.versioning.compatibility as compat_module

    def _boom(self, *args, **kwargs):
        raise RuntimeError("simulated analyzer failure")

    monkeypatch.setattr(compat_module.CompatibilityAnalysisService, "analyze", _boom)

    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _create_version(client, org, agent["id"])

    published = _publish(client, org, agent["id"], version["id"])
    assert published["status"] == "PUBLISHED"


def test_analyze_endpoint_recomputes_for_a_previously_published_version(client: TestClient,
                                                                         db_session: Session) -> None:
    """AC-35."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    _create_version(client, org, agent["id"])
    v2 = _create_version(client, org, agent["id"], model_configuration={"provider": "ANTHROPIC", "model": "mock-model"})
    published = _publish(client, org, agent["id"], v2["id"])
    assert published["compatibility_level"] == "BREAKING"  # already analyzed automatically at publish

    # Simulate "published before this phase existed" by clearing the analysis.
    row = db_session.get(AgentVersion, uuid.UUID(v2["id"]))
    row.compatibility_level = "UNKNOWN"
    row.compatibility_analyzed_at = None
    row.compatibility_baseline_id = None
    db_session.commit()

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{v2['id']}", headers=org["headers"])
    assert r.json()["compatibility_level"] == "UNKNOWN"

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{v2['id']}/compatibility/analyze", headers=org["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["compatibility_level"] == "BREAKING"


def test_analysis_completes_within_two_seconds(client: TestClient) -> None:
    """AC-36."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    _create_version(client, org, agent["id"])
    v2 = _create_version(client, org, agent["id"], model_configuration={"provider": "ANTHROPIC", "model": "mock-model"})

    start = time.perf_counter()
    r = client.post(f"{RT}/agents/{agent['id']}/versions/{v2['id']}/compatibility/analyze", headers=org["headers"])
    elapsed = time.perf_counter() - start
    assert r.status_code == 200, r.text
    assert elapsed < 2.0


def test_input_output_contract_diffing_uses_agent_definition_schemas(client: TestClient,
                                                                      db_session: Session) -> None:
    """End-to-end proof that the service layer reads AgentDefinition.input_
    schema/output_schema (the §4.2 data-source decision), not just the pure
    function in isolation."""
    org = _register_org(client)
    agent = _register_agent(client, org, input_schema={
        "properties": {"customer_id": {"type": "string"}}, "required": ["customer_id"],
    })
    definitions = client.get(f"{RT}/agents/{agent['id']}/definitions", headers=org["headers"]).json()
    baseline_definition_id = definitions[0]["id"]
    candidate_definition_id = _add_definition(db_session, agent["id"],
                                              input_schema={"properties": {}, "required": []})

    v1 = _create_version(client, org, agent["id"], definition_id=baseline_definition_id)
    v2 = _create_version(client, org, agent["id"], definition_id=candidate_definition_id)

    report = CompatibilityAnalysisService(db_session).analyze(uuid.UUID(v2["id"]), agent_id=uuid.UUID(agent["id"]))
    assert str(report["baseline_version_id"]) == v1["id"]
    assert report["compatibility_level"] == "BREAKING"
    assert any(f["path"] == "inputs.customer_id" and f["change_type"] == "REMOVED" for f in report["findings"])


# =========================================================================== #
# API — shapes, permissions, error codes (AC-31, AC-33, AC-34)
# =========================================================================== #
def test_compatibility_report_shape_and_summary_counts(client: TestClient) -> None:
    """AC-31."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    _create_version(client, org, agent["id"], model_configuration={"provider": "MOCK", "model": "mock-model"})
    v2 = _create_version(client, org, agent["id"],
                         model_configuration={"provider": "ANTHROPIC", "model": "mock-model", "temperature": 0.9})

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{v2['id']}/compatibility/analyze", headers=org["headers"])
    assert r.status_code == 200, r.text
    report = r.json()
    for key in ("candidate_version_id", "baseline_version_id", "compatibility_level", "declared_semver",
               "declared_increment", "expected_increment", "semver_consistent", "analyzed_at", "summary",
               "findings"):
        assert key in report
    assert report["summary"]["breaking"] >= 1
    provider_finding = next(f for f in report["findings"] if f["path"] == "model_configuration.provider")
    assert "re-validated" in provider_finding["description"]


def test_endpoints_enforce_permission_and_return_shapes(client: TestClient) -> None:
    """AC-33."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _create_version(client, org, agent["id"])

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/compatibility", headers=org["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["compatibility_level"] == "UNKNOWN"  # never analyzed yet -- still DRAFT

    r = client.post(f"{RT}/agents/{agent['id']}/versions/{version['id']}/compatibility/analyze",
                    headers=org["headers"])
    assert r.status_code == 200, r.text

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/compatibility/findings",
                   headers=org["headers"])
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)

    # No credentials at all -- rejected, not silently allowed.
    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/compatibility")
    assert r.status_code in (401, 403)


def test_unknown_version_404_and_baseline_not_found_error_code(client: TestClient) -> None:
    """AC-34."""
    org = _register_org(client)
    agent = _register_agent(client, org)
    version = _create_version(client, org, agent["id"])

    fake_version_id = str(uuid.uuid4())
    r = client.get(f"{RT}/agents/{agent['id']}/versions/{fake_version_id}/compatibility", headers=org["headers"])
    assert r.status_code == 404

    other_agent = _register_agent(client, org)
    other_version = _create_version(client, org, other_agent["id"])
    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/compatibility", headers=org["headers"],
                   params={"baseline_version_id": other_version["id"]})
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "COMPATIBILITY_BASELINE_NOT_FOUND"


def test_cross_tenant_compatibility_lookup_denied(client: TestClient) -> None:
    """AC-42 (ACT-PLT-NFR-001)."""
    org_a = _register_org(client, "Compat Org A")
    org_b = _register_org(client, "Compat Org B")
    agent = _register_agent(client, org_a)
    version = _create_version(client, org_a, agent["id"])

    r = client.get(f"{RT}/agents/{agent['id']}/versions/{version['id']}/compatibility", headers=org_b["headers"])
    assert r.status_code == 404
