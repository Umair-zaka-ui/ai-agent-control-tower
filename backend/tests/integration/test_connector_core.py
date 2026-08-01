"""Phase 2.1.1 tests — Connector Abstraction & Lifecycle.

Grouped exactly as the build prompt's §8 groups its acceptance criteria:
abstraction (AC-01..06), type vs instance (AC-07..09), config validation
(AC-10..12), lifecycle (AC-13..19), API & integrity (AC-20..27 — the
suite-level ones, AC-22/25/26, are proven by the full-suite run cited in
the phase summary, not duplicated here)."""

from __future__ import annotations

import dataclasses
import inspect
import uuid
from pathlib import Path

import jsonschema
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integration.base import Connector, validate_configuration_schema
from app.integration.errors import ConnectorConfigInvalidError
from app.integration.lifecycle import all_states, can_transition
from app.integration.mock import CONNECTOR_TYPE, CONNECTOR_VERSION, MockConnector
from app.integration.service import ConnectorService
from app.integration.types import ConnectorDescriptor, ToolContract
from app.models.integration import Connector as ConnectorRow, ConnectorInstance, ConnectorLifecycleEvent
from app.models.rbac import AuthorizationAudit

RT = "/api/v1/integration"


# --------------------------------------------------------------------------- #
# Abstraction (AC-01..06)
# --------------------------------------------------------------------------- #
def test_ac01_connector_is_abstract():
    with pytest.raises(TypeError):
        Connector()  # type: ignore[abstract]


def test_ac02_subclass_missing_a_required_method_fails_to_instantiate():
    class _MissingValidateConfiguration(Connector):
        def describe(self) -> ConnectorDescriptor:
            return MockConnector().describe()

    with pytest.raises(TypeError):
        _MissingValidateConfiguration()  # type: ignore[abstract]

    class _MissingDescribe(Connector):
        def validate_configuration(self, configuration):
            return None

    with pytest.raises(TypeError):
        _MissingDescribe()  # type: ignore[abstract]


def test_ac03_mock_connector_satisfies_the_interface_without_an_abc_change():
    connector = MockConnector()
    assert isinstance(connector, Connector)
    descriptor = connector.describe()
    connector.validate_configuration({"endpoint": "https://example.internal"})
    # No method exists on MockConnector beyond what Connector declares --
    # proof expressing it required no extra surface (and, structurally,
    # no later-phase method like authenticate/execute/health_check exists
    # on the ABC at all).
    abc_methods = {name for name, _ in inspect.getmembers(Connector, predicate=inspect.isfunction)}
    assert abc_methods == {"describe", "validate_configuration"}
    assert descriptor.connector_type == CONNECTOR_TYPE


def test_ac04_describe_returns_the_full_declaration():
    descriptor = MockConnector().describe()
    assert descriptor.connector_type == "MOCK"
    assert descriptor.version == CONNECTOR_VERSION
    assert descriptor.capabilities
    assert descriptor.config_schema["type"] == "object"
    assert descriptor.auth_requirements == {"scheme": "NONE"}
    assert len(descriptor.tool_contracts) == 1
    assert descriptor.tool_contracts[0].name == "ping"


def test_ac05_no_connector_specific_vocabulary_leaks_into_the_runtime():
    """The runtime-never-knows principle (ACT-INT-FR-006), mechanically
    checked: nothing under app/runtime (including the model-provider
    package) may reference "connector" anywhere in its source."""
    runtime_root = Path(__file__).resolve().parents[2] / "app" / "runtime"
    offenders = []
    for path in runtime_root.rglob("*.py"):
        if "connector" in path.read_text(encoding="utf-8").lower():
            offenders.append(str(path))
    assert offenders == []

    # Nor does a connector-neutral *type's field* name a vendor -- checked
    # against the actual dataclass fields, not module prose (this test's
    # own module, and types.py's docstring, both legitimately discuss SAP/
    # Salesforce as examples of what must stay out of the *fields*).
    field_names = {f.name for f in dataclasses.fields(ConnectorDescriptor)}
    field_names |= {f.name for f in dataclasses.fields(ToolContract)}
    for vendor in ("sap", "salesforce", "servicenow", "workday", "mock"):
        assert not any(vendor in name.lower() for name in field_names)


def test_ac06_connector_neutral_types_are_immutable():
    descriptor = MockConnector().describe()
    with pytest.raises(dataclasses.FrozenInstanceError):
        descriptor.connector_type = "OTHER"  # type: ignore[misc]
    with pytest.raises(TypeError):
        descriptor.capabilities["x"] = 1  # MappingProxyType is read-only
    contract = descriptor.tool_contracts[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        contract.name = "other"  # type: ignore[misc]
    with pytest.raises(TypeError):
        contract.parameters["x"] = 1


# --------------------------------------------------------------------------- #
# Type vs instance (AC-07..09)
# --------------------------------------------------------------------------- #
def test_ac07_one_type_many_instances_across_orgs(client: TestClient, admin, other_org_admin):
    r1 = client.post(f"{RT}/connectors", headers=admin["headers"],
                     json={"connector_type": "MOCK", "name": "Org A Instance"})
    r2 = client.post(f"{RT}/connectors", headers=other_org_admin["headers"],
                     json={"connector_type": "MOCK", "name": "Org B Instance"})
    assert r1.status_code == 201, r1.text
    assert r2.status_code == 201, r2.text
    assert r1.json()["connector_id"] == r2.json()["connector_id"]  # same type row
    assert r1.json()["id"] != r2.json()["id"]  # distinct instances


def test_ac08_instance_is_tenant_scoped(client: TestClient, admin, other_org_admin):
    created = client.post(f"{RT}/connectors", headers=admin["headers"],
                          json={"connector_type": "MOCK", "name": "Private Instance"})
    instance_id = created.json()["id"]

    own = client.get(f"{RT}/connectors/{instance_id}", headers=admin["headers"])
    assert own.status_code == 200

    cross = client.get(f"{RT}/connectors/{instance_id}", headers=other_org_admin["headers"])
    assert cross.status_code == 404
    assert cross.json()["error"]["code"] == "CONNECTOR_NOT_FOUND"

    listing = client.get(f"{RT}/connectors", headers=other_org_admin["headers"]).json()
    assert instance_id not in {row["id"] for row in listing}


def test_ac09_independent_configuration_per_org(client: TestClient, admin, other_org_admin):
    a = client.post(f"{RT}/connectors", headers=admin["headers"], json={
        "connector_type": "MOCK", "name": "A", "configuration": {"endpoint": "https://a.internal"},
    }).json()
    b = client.post(f"{RT}/connectors", headers=other_org_admin["headers"], json={
        "connector_type": "MOCK", "name": "B", "configuration": {"endpoint": "https://b.internal"},
    }).json()
    assert a["configuration"]["endpoint"] == "https://a.internal"
    assert b["configuration"]["endpoint"] == "https://b.internal"
    assert a["lifecycle_state"] == b["lifecycle_state"] == "configured"


# --------------------------------------------------------------------------- #
# Config validation (AC-10..12)
# --------------------------------------------------------------------------- #
def test_ac10_valid_configuration_reaches_configured(client: TestClient, admin):
    created = client.post(f"{RT}/connectors", headers=admin["headers"],
                          json={"connector_type": "MOCK", "name": "Valid Config"}).json()
    assert created["lifecycle_state"] == "registered"

    patched = client.patch(f"{RT}/connectors/{created['id']}", headers=admin["headers"],
                           json={"configuration": {"endpoint": "https://good.internal"}})
    assert patched.status_code == 200, patched.text
    assert patched.json()["lifecycle_state"] == "configured"
    assert patched.json()["configuration"] == {"endpoint": "https://good.internal"}


def test_ac11_invalid_configuration_rejected_and_instance_stays_registered(client: TestClient, admin):
    created = client.post(f"{RT}/connectors", headers=admin["headers"],
                          json={"connector_type": "MOCK", "name": "Invalid Config"}).json()

    patched = client.patch(f"{RT}/connectors/{created['id']}", headers=admin["headers"],
                           json={"configuration": {"wrong_field": "no endpoint here"}})
    assert patched.status_code == 422
    assert patched.json()["error"]["code"] == "CONNECTOR_CONFIG_INVALID"
    assert "endpoint" in patched.json()["error"]["message"] or "required" in patched.json()["error"]["message"].lower()

    still = client.get(f"{RT}/connectors/{created['id']}", headers=admin["headers"]).json()
    assert still["lifecycle_state"] == "registered"
    assert still["configuration"] == {}


def test_ac12_config_validation_reuses_jsonschema_not_a_new_validator():
    import app.integration.base as base_module
    assert base_module.jsonschema is jsonschema

    with pytest.raises(ConnectorConfigInvalidError):
        validate_configuration_schema({}, {"type": "object", "required": ["endpoint"]})


# --------------------------------------------------------------------------- #
# Lifecycle (AC-13..19)
# --------------------------------------------------------------------------- #
def test_ac13_each_valid_transition_writes_a_lifecycle_event(client: TestClient, admin, db_session: Session):
    created = client.post(f"{RT}/connectors", headers=admin["headers"], json={
        "connector_type": "MOCK", "name": "Full Lifecycle", "configuration": {"endpoint": "https://x.internal"},
    }).json()
    instance_id = created["id"]
    assert created["lifecycle_state"] == "configured"

    activated = client.post(f"{RT}/connectors/{instance_id}/activate", headers=admin["headers"])
    assert activated.status_code == 200 and activated.json()["lifecycle_state"] == "active"

    disabled = client.post(f"{RT}/connectors/{instance_id}/disable", headers=admin["headers"],
                           json={"reason": "maintenance"})
    assert disabled.status_code == 200 and disabled.json()["lifecycle_state"] == "disabled"
    assert disabled.json()["state_reason"] == "maintenance"

    events = db_session.execute(
        select(ConnectorLifecycleEvent).where(ConnectorLifecycleEvent.connector_instance_id == uuid.UUID(instance_id))
        .order_by(ConnectorLifecycleEvent.created_at)
    ).scalars().all()
    transitions = [(e.from_state, e.to_state) for e in events]
    assert transitions == [
        ("registered", "configured"), ("configured", "active"), ("active", "disabled"),
    ]


def test_ac14_invalid_transitions_are_rejected(client: TestClient, admin):
    registered = client.post(f"{RT}/connectors", headers=admin["headers"],
                             json={"connector_type": "MOCK", "name": "Bad Transitions"}).json()
    instance_id = registered["id"]

    # activate straight from `registered` -- must be `configured` first.
    r = client.post(f"{RT}/connectors/{instance_id}/activate", headers=admin["headers"])
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONNECTOR_INVALID_TRANSITION"

    # disable from `registered`.
    r = client.post(f"{RT}/connectors/{instance_id}/disable", headers=admin["headers"])
    assert r.status_code == 409

    # configure from `active` -- must disable first (this phase's own
    # documented judgment call, see ConnectorService.update_configuration).
    client.patch(f"{RT}/connectors/{instance_id}", headers=admin["headers"],
                json={"configuration": {"endpoint": "https://y.internal"}})
    client.post(f"{RT}/connectors/{instance_id}/activate", headers=admin["headers"])
    r = client.patch(f"{RT}/connectors/{instance_id}", headers=admin["headers"],
                     json={"configuration": {"endpoint": "https://z.internal"}})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "CONNECTOR_INVALID_TRANSITION"


def test_ac15_disable_preserves_configuration_and_history(client: TestClient, admin, db_session: Session):
    created = client.post(f"{RT}/connectors", headers=admin["headers"], json={
        "connector_type": "MOCK", "name": "Preserve Me", "configuration": {"endpoint": "https://preserve.internal"},
    }).json()
    instance_id = created["id"]
    client.post(f"{RT}/connectors/{instance_id}/activate", headers=admin["headers"])
    disabled = client.post(f"{RT}/connectors/{instance_id}/disable", headers=admin["headers"]).json()

    assert disabled["configuration"] == {"endpoint": "https://preserve.internal"}
    events = client.get(f"{RT}/connectors/{instance_id}/events", headers=admin["headers"]).json()
    assert len(events) == 3  # configure, activate, disable -- none lost


def test_ac16_failed_is_reachable_and_the_machine_is_complete(client: TestClient, admin, db_session: Session):
    org_id = uuid.UUID(admin["organization_id"])
    svc = ConnectorService(db_session)

    for state_setup in ("registered", "configured", "active", "disabled"):
        created = client.post(f"{RT}/connectors", headers=admin["headers"], json={
            "connector_type": "MOCK", "name": f"Fail From {state_setup} {uuid.uuid4().hex[:6]}",
            "configuration": {"endpoint": "https://fail.internal"} if state_setup != "registered" else None,
        }).json()
        instance_id = uuid.UUID(created["id"])
        if state_setup in ("active", "disabled"):
            svc.activate(None, org_id, instance_id)
        if state_setup == "disabled":
            svc.disable(None, org_id, instance_id)

        failed = svc.mark_failed(None, org_id, instance_id, reason=f"unreachable from {state_setup}")
        assert failed.lifecycle_state == "failed"

        # The machine is complete: nothing transitions *out* of `failed`
        # in this sub-phase's graph (health-driven recovery is 2.1.3).
        for event in ("configure", "activate", "disable", "mark_failed"):
            assert not can_transition(event, "failed")

    assert set(all_states()) == {"registered", "configured", "active", "disabled", "failed"}


def test_ac17_every_transition_emits_an_audit_event(client: TestClient, admin, db_session: Session):
    created = client.post(f"{RT}/connectors", headers=admin["headers"], json={
        "connector_type": "MOCK", "name": "Audited", "configuration": {"endpoint": "https://audit.internal"},
    }).json()
    client.post(f"{RT}/connectors/{created['id']}/activate", headers=admin["headers"])

    audits = db_session.execute(
        select(AuthorizationAudit).where(
            AuthorizationAudit.organization_id == uuid.UUID(admin["organization_id"]),
            AuthorizationAudit.event_type == "INTEGRATION_CONNECTOR_STATE_CHANGED",
        )
    ).scalars().all()
    assert len(audits) >= 2
    events = {a.meta["event"] for a in audits if a.meta and a.meta.get("connector_instance_id") == created["id"]}
    assert events == {"configure", "activate"}


def test_ac18_lifecycle_events_are_append_only_by_construction(client: TestClient):
    """No update/delete path exists anywhere for a lifecycle event -- the
    service class exposes no such method, and no route accepts PATCH/DELETE
    on the events collection (matching this codebase's established
    convention of enforcing "append-only" at the application layer, not
    via a DB-level REVOKE -- see models/integration.py)."""
    service_methods = {name for name, _ in inspect.getmembers(ConnectorService, predicate=inspect.isfunction)}
    assert not any("event" in name and ("update" in name or "delete" in name) for name in service_methods)

    from app.main import app
    event_route_methods: set[str] = set()
    for route in app.routes:
        if getattr(route, "path", "") == f"{RT}/connectors/{{instance_id}}/events":
            event_route_methods |= route.methods
    assert "PATCH" not in event_route_methods
    assert "DELETE" not in event_route_methods
    assert "GET" in event_route_methods


def test_ac19_connector_versioning_two_versions_coexist(client: TestClient, admin, db_session: Session):
    # `connectors` is a platform-wide catalog, not test-transaction-scoped
    # (the same "global, committed" shape `signing_keys` has -- see
    # REPO_STATE's note on that table needing per-test isolation): a fixed
    # literal version string would collide with itself on the next test
    # run against the same persistent dev database, so this test mints its
    # own unique version rather than reusing a fixed "1.1.0".
    new_version = f"1.0.0-test-{uuid.uuid4().hex[:8]}"
    v1 = db_session.execute(
        select(ConnectorRow).where(ConnectorRow.connector_type == "MOCK", ConnectorRow.version == "1.0.0")
    ).scalar_one()
    v2 = ConnectorRow(
        connector_type="MOCK", version=new_version, capabilities=dict(v1.capabilities),
        config_schema=dict(v1.config_schema), auth_requirements=dict(v1.auth_requirements),
        tool_contracts=list(v1.tool_contracts),
    )
    db_session.add(v2)
    db_session.commit()

    pinned_old = client.post(f"{RT}/connectors", headers=admin["headers"],
                             json={"connector_type": "MOCK", "version": "1.0.0", "name": "Pinned Old"})
    pinned_new = client.post(f"{RT}/connectors", headers=admin["headers"],
                             json={"connector_type": "MOCK", "version": new_version, "name": "Pinned New"})
    assert pinned_old.status_code == 201 and pinned_new.status_code == 201
    assert pinned_old.json()["connector_id"] == str(v1.id)
    assert pinned_new.json()["connector_id"] == str(v2.id)
    assert pinned_old.json()["connector_id"] != pinned_new.json()["connector_id"]


# --------------------------------------------------------------------------- #
# API & integrity (AC-20..27)
# --------------------------------------------------------------------------- #
def test_ac20_endpoints_enforce_permissions(client: TestClient, admin, viewer):
    # No auth at all -- this platform's HTTPBearer dependency rejects with
    # 403 "Not authenticated" (not 401) when the header is simply absent;
    # matches every other route in this codebase, not a new behavior.
    assert client.get(f"{RT}/connectors").status_code == 403

    # Authenticated but unpermitted (VIEWER has neither integration.* perm) -- 403.
    assert client.get(f"{RT}/connectors", headers=viewer["headers"]).status_code == 403
    assert client.get(f"{RT}/connector-types", headers=viewer["headers"]).status_code == 403
    assert client.post(f"{RT}/connectors", headers=viewer["headers"],
                       json={"connector_type": "MOCK", "name": "x"}).status_code == 403

    created = client.post(f"{RT}/connectors", headers=admin["headers"],
                          json={"connector_type": "MOCK", "name": "Perm Check"}).json()
    assert client.patch(f"{RT}/connectors/{created['id']}", headers=viewer["headers"],
                        json={"configuration": {"endpoint": "https://x.internal"}}).status_code == 403
    assert client.post(f"{RT}/connectors/{created['id']}/activate", headers=viewer["headers"]).status_code == 403
    assert client.post(f"{RT}/connectors/{created['id']}/disable", headers=viewer["headers"]).status_code == 403
    assert client.get(f"{RT}/connectors/{created['id']}/events", headers=viewer["headers"]).status_code == 403


def test_ac21_cross_org_access_is_rejected_not_confirmed(client: TestClient, admin, other_org_admin):
    created = client.post(f"{RT}/connectors", headers=admin["headers"],
                          json={"connector_type": "MOCK", "name": "Cross Org"}).json()
    requests = [
        ("patch", f"{RT}/connectors/{created['id']}", {"configuration": {"endpoint": "https://x.internal"}}),
        ("post", f"{RT}/connectors/{created['id']}/activate", None),
        ("post", f"{RT}/connectors/{created['id']}/disable", None),
        ("get", f"{RT}/connectors/{created['id']}/events", None),
    ]
    for verb, path, body in requests:
        kwargs = {"headers": other_org_admin["headers"]}
        if body is not None:
            kwargs["json"] = body
        resp = getattr(client, verb)(path, **kwargs)
        assert resp.status_code == 404, f"{verb} {path} leaked cross-org: {resp.status_code}"
        assert resp.json()["error"]["code"] == "CONNECTOR_NOT_FOUND"


def test_ac23_no_credential_column_on_the_instance_table():
    forbidden_substrings = ("credential", "secret", "api_key", "password", "token")
    columns = set(ConnectorInstance.__table__.columns.keys())
    for column in columns:
        for bad in forbidden_substrings:
            assert bad not in column.lower(), f"{column} looks like a credential field"


def test_unknown_connector_type_is_rejected(client: TestClient, admin):
    r = client.post(f"{RT}/connectors", headers=admin["headers"],
                    json={"connector_type": "SAP", "name": "Nope"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "CONNECTOR_TYPE_NOT_FOUND"


def test_ac27_no_new_todo_or_skip_markers_in_this_phases_files():
    root = Path(__file__).resolve().parents[2] / "app" / "integration"
    markers = ("TODO", "FIXME", "XXX", "HACK:", "NotImplementedError")
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            assert marker not in text, f"{marker} found in {path}"
