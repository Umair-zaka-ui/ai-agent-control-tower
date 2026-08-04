"""Phase 2.1.3 tests — Connector Registry & Health.

Grouped exactly as the build prompt's §8 groups its acceptance criteria:
registry (AC-01..04), health check (AC-05..10), transition & fail-fast
(AC-11..15), history & alerting (AC-16..18), scheduler & integrity
(AC-19..27 — the suite-level ones, AC-22/25/26, are proven by the
full-suite run cited in the phase summary, not duplicated here)."""

from __future__ import annotations

import inspect
import json
import logging
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.integration import scheduler
from app.integration.base import Connector
from app.integration.errors import ConnectorNotFoundError, ConnectorUnavailableError
from app.integration.registry import ConnectorRegistry
from app.models.integration import ConnectorHealthCheck, ConnectorInstance
from app.models.rbac import AuthorizationAudit
from app.models.user import User

RT = "/api/v1/integration"


# --------------------------------------------------------------------------- #
# Helpers (local copies, matching this directory's established convention)
# --------------------------------------------------------------------------- #
def _create_mock_instance(
    client: TestClient, admin: dict, *, name: str | None = None, configuration: dict[str, Any] | None = None,
) -> dict:
    r = client.post(f"{RT}/connectors", headers=admin["headers"], json={
        "connector_type": "MOCK", "name": name or f"Health MOCK {uuid.uuid4().hex[:6]}",
        "configuration": configuration or {"endpoint": "https://mock.internal"},
    })
    assert r.status_code == 201, r.text
    return r.json()


def _create_mock_auth_instance(client: TestClient, admin: dict, *, name: str | None = None) -> dict:
    r = client.post(f"{RT}/connectors", headers=admin["headers"], json={
        "connector_type": "MOCK_AUTH", "name": name or f"Health MOCK_AUTH {uuid.uuid4().hex[:6]}",
        "configuration": {"endpoint": "https://mockauth.internal"},
    })
    assert r.status_code == 201, r.text
    return r.json()


def _drive_to_failed(client: TestClient, admin: dict, db_session: Session, instance: dict) -> None:
    """Activates, then simulates the *external* endpoint going down by
    mutating the stored row directly rather than via PATCH (which 2.1.1
    correctly forbids while active) — a real outage needs no local
    config change at all, so bypassing the config-management API here is
    the accurate simulation, not a workaround for a restriction under
    test elsewhere."""
    activated = client.post(f"{RT}/connectors/{instance['id']}/activate", headers=admin["headers"])
    assert activated.status_code == 200, activated.text
    row = db_session.get(ConnectorInstance, uuid.UUID(instance["id"]))
    row.configuration = {**row.configuration, "simulate_unreachable": True}
    db_session.commit()
    check = client.post(f"{RT}/connectors/{instance['id']}/health/check", headers=admin["headers"])
    assert check.status_code == 200 and check.json()["result"] == "UNHEALTHY", check.text


# --------------------------------------------------------------------------- #
# Registry (AC-01..04)
# --------------------------------------------------------------------------- #
def test_ac01_registry_resolves_type(db_session: Session):
    row = ConnectorRegistry(db_session).resolve_type("MOCK")
    assert row.connector_type == "MOCK"


def test_ac02_registry_resolves_instance_config_type_and_credential_reference(
    client: TestClient, admin: dict, db_session: Session,
):
    instance = _create_mock_auth_instance(client, admin)
    resolved = ConnectorRegistry(db_session).resolve_instance_for_invocation(
        uuid.UUID(admin["organization_id"]), uuid.UUID(instance["id"]),
    )
    assert resolved.connector_type == "MOCK_AUTH"
    assert resolved.auth_scheme == "API_KEY"
    assert resolved.configuration["endpoint"] == "https://mockauth.internal"


def test_ac03_listing_types_platform_wide_instances_tenant_scoped(
    client: TestClient, admin: dict, other_org_admin: dict, db_session: Session,
):
    a = _create_mock_instance(client, admin)
    b = _create_mock_instance(client, other_org_admin)
    registry = ConnectorRegistry(db_session)

    types = registry.list_types()
    assert any(t.connector_type == "MOCK" for t in types)

    org_a_instances = registry.list_instances(uuid.UUID(admin["organization_id"]))
    assert any(str(i.id) == a["id"] for i in org_a_instances)
    assert not any(str(i.id) == b["id"] for i in org_a_instances)


def test_ac04_instance_resolution_is_tenant_isolated(
    client: TestClient, admin: dict, other_org_admin: dict, db_session: Session,
):
    instance = _create_mock_instance(client, admin)
    with pytest.raises(ConnectorNotFoundError):
        ConnectorRegistry(db_session).resolve_instance_for_invocation(
            uuid.UUID(other_org_admin["organization_id"]), uuid.UUID(instance["id"]),
        )


# --------------------------------------------------------------------------- #
# Health check (AC-05..10)
# --------------------------------------------------------------------------- #
def test_ac05_on_demand_check_runs_and_records_a_row(client: TestClient, admin: dict, db_session: Session):
    instance = _create_mock_instance(client, admin)
    r = client.post(f"{RT}/connectors/{instance['id']}/health/check", headers=admin["headers"])
    assert r.status_code == 200, r.text
    count = db_session.execute(
        select(func.count()).select_from(ConnectorHealthCheck)
        .where(ConnectorHealthCheck.connector_instance_id == uuid.UUID(instance["id"]))
    ).scalar()
    assert count == 1


def test_ac06_healthy_and_unhealthy_mock_paths(client: TestClient, admin: dict):
    healthy_instance = _create_mock_instance(client, admin)
    r = client.post(f"{RT}/connectors/{healthy_instance['id']}/health/check", headers=admin["headers"])
    assert r.json()["result"] == "HEALTHY"

    unhealthy_instance = _create_mock_instance(
        client, admin, configuration={"endpoint": "https://mock.internal", "simulate_unreachable": True},
    )
    r2 = client.post(f"{RT}/connectors/{unhealthy_instance['id']}/health/check", headers=admin["headers"])
    assert r2.json()["result"] == "UNHEALTHY"


def test_ac07_check_verifies_reachability_and_auth_validity_separately(client: TestClient, admin: dict):
    configured = _create_mock_auth_instance(client, admin)
    client.put(f"{RT}/connectors/{configured['id']}/credentials", headers=admin["headers"],
              json={"auth_scheme": "API_KEY", "credential": {"api_key": "sk-good-check"}})
    r = client.post(f"{RT}/connectors/{configured['id']}/health/check", headers=admin["headers"])
    body = r.json()
    assert body["reachable"] is True
    assert body["auth_valid"] is True
    assert body["result"] == "HEALTHY"

    unconfigured = _create_mock_auth_instance(client, admin)
    r2 = client.post(f"{RT}/connectors/{unconfigured['id']}/health/check", headers=admin["headers"])
    body2 = r2.json()
    assert body2["reachable"] is True
    assert body2["auth_valid"] is False
    assert body2["result"] == "UNHEALTHY"


def test_ac08_health_check_result_contains_no_credential_material(
    client: TestClient, admin: dict, db_session: Session, caplog,
):
    instance = _create_mock_auth_instance(client, admin)
    secret_value = "sk-health-check-secret-9f8e7d"
    client.put(f"{RT}/connectors/{instance['id']}/credentials", headers=admin["headers"],
              json={"auth_scheme": "API_KEY", "credential": {"api_key": secret_value}})

    with caplog.at_level(logging.DEBUG):
        r = client.post(f"{RT}/connectors/{instance['id']}/health/check", headers=admin["headers"])
    assert secret_value not in r.text
    all_log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert secret_value not in all_log_text

    audits = db_session.execute(
        select(AuthorizationAudit).where(AuthorizationAudit.event_type == "INTEGRATION_CONNECTOR_HEALTH_CHECKED")
    ).scalars().all()
    assert all(secret_value not in json.dumps(a.meta or {}) for a in audits)

    row = db_session.execute(
        select(ConnectorHealthCheck).where(ConnectorHealthCheck.connector_instance_id == uuid.UUID(instance["id"]))
    ).scalar_one()
    assert secret_value not in (row.reason or "")


def test_ac09_execution_error_is_error_not_unhealthy(client: TestClient, admin: dict, db_session: Session):
    instance = _create_mock_instance(
        client, admin, configuration={"endpoint": "https://mock.internal", "simulate_error": True},
    )
    r = client.post(f"{RT}/connectors/{instance['id']}/health/check", headers=admin["headers"])
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "CONNECTOR_HEALTH_CHECK_FAILED"

    row = db_session.execute(
        select(ConnectorHealthCheck).where(ConnectorHealthCheck.connector_instance_id == uuid.UUID(instance["id"]))
    ).scalar_one()
    assert row.result == "ERROR"


def test_ac10_instance_health_cache_updates_after_a_check(client: TestClient, admin: dict):
    instance = _create_mock_instance(client, admin)
    before = client.get(f"{RT}/connectors/{instance['id']}/health", headers=admin["headers"]).json()
    assert before["current_health"] is None
    assert before["last_health_check_at"] is None

    client.post(f"{RT}/connectors/{instance['id']}/health/check", headers=admin["headers"])

    after = client.get(f"{RT}/connectors/{instance['id']}/health", headers=admin["headers"]).json()
    assert after["current_health"] == "HEALTHY"
    assert after["last_health_check_at"] is not None


# --------------------------------------------------------------------------- #
# Transition & fail-fast (AC-11..15)
# --------------------------------------------------------------------------- #
def test_ac11_failing_check_transitions_active_to_failed(client: TestClient, admin: dict, db_session: Session):
    instance = _create_mock_instance(client, admin)
    _drive_to_failed(client, admin, db_session, instance)

    updated = client.get(f"{RT}/connectors/{instance['id']}", headers=admin["headers"]).json()
    assert updated["lifecycle_state"] == "failed"
    assert updated["state_reason"]

    events = client.get(f"{RT}/connectors/{instance['id']}/events", headers=admin["headers"]).json()
    assert any(e["from_state"] == "active" and e["to_state"] == "failed" for e in events)


def test_ac12_passing_check_recovers_failed_to_active(client: TestClient, admin: dict, db_session: Session):
    instance = _create_mock_instance(client, admin)
    _drive_to_failed(client, admin, db_session, instance)

    row = db_session.get(ConnectorInstance, uuid.UUID(instance["id"]))
    row.configuration = {**row.configuration, "simulate_unreachable": False}
    db_session.commit()

    r = client.post(f"{RT}/connectors/{instance['id']}/health/check", headers=admin["headers"])
    assert r.json()["result"] == "HEALTHY"

    updated = client.get(f"{RT}/connectors/{instance['id']}", headers=admin["headers"]).json()
    assert updated["lifecycle_state"] == "active"

    events = client.get(f"{RT}/connectors/{instance['id']}/events", headers=admin["headers"]).json()
    assert any(e["from_state"] == "failed" and e["to_state"] == "active" for e in events)


def test_ac13_resolving_a_failed_connector_fails_fast(client: TestClient, admin: dict, db_session: Session):
    instance = _create_mock_instance(client, admin)
    _drive_to_failed(client, admin, db_session, instance)

    with pytest.raises(ConnectorUnavailableError):
        ConnectorRegistry(db_session).resolve_instance_for_invocation(
            uuid.UUID(admin["organization_id"]), uuid.UUID(instance["id"]),
        )


def test_ac14_resolving_a_disabled_connector_fails_fast(client: TestClient, admin: dict, db_session: Session):
    instance = _create_mock_instance(client, admin)
    client.post(f"{RT}/connectors/{instance['id']}/activate", headers=admin["headers"])
    disabled = client.post(f"{RT}/connectors/{instance['id']}/disable", headers=admin["headers"])
    assert disabled.status_code == 200

    with pytest.raises(ConnectorUnavailableError):
        ConnectorRegistry(db_session).resolve_instance_for_invocation(
            uuid.UUID(admin["organization_id"]), uuid.UUID(instance["id"]),
        )


def test_ac15_transitions_go_through_the_state_machine_not_a_bypass():
    import re

    from app.integration import lifecycle

    assert lifecycle.can_transition("mark_failed", "active")
    assert lifecycle.can_transition("recover", "failed")

    source = (Path(__file__).resolve().parents[2] / "app" / "integration" / "health.py").read_text(encoding="utf-8")
    # Matches an *assignment* to .lifecycle_state (single `=`, not `==`
    # comparison) -- health.py only ever reads it, never writes it
    # directly; every actual transition goes through
    # ConnectorService.mark_failed/recover.
    assert re.search(r"\.lifecycle_state\s*=(?!=)", source) is None
    assert "mark_failed(" in source and "recover(" in source


# --------------------------------------------------------------------------- #
# History & alerting (AC-16..18)
# --------------------------------------------------------------------------- #
def test_ac16_history_is_queryable_and_ordered(client: TestClient, admin: dict):
    instance = _create_mock_instance(client, admin)
    for _ in range(3):
        r = client.post(f"{RT}/connectors/{instance['id']}/health/check", headers=admin["headers"])
        assert r.status_code == 200

    history = client.get(f"{RT}/connectors/{instance['id']}/health/history", headers=admin["headers"]).json()
    assert len(history) == 3
    timestamps = [h["checked_at"] for h in history]
    assert timestamps == sorted(timestamps, reverse=True)  # newest first -- "since when failing" answerable


def test_ac17_history_is_append_only_and_bounded(
    client: TestClient, admin: dict, db_session: Session, monkeypatch,
):
    import app.integration.health as health_module

    monkeypatch.setattr(health_module, "_HEALTH_HISTORY_RETENTION", 3)
    instance = _create_mock_instance(client, admin)
    for _ in range(6):
        r = client.post(f"{RT}/connectors/{instance['id']}/health/check", headers=admin["headers"])
        assert r.status_code == 200

    count = db_session.execute(
        select(func.count()).select_from(ConnectorHealthCheck)
        .where(ConnectorHealthCheck.connector_instance_id == uuid.UUID(instance["id"]))
    ).scalar()
    assert count == 3  # bounded, oldest rolled off

    from app.main import app
    methods: set[str] = set()
    for route in app.routes:
        if getattr(route, "path", "") == f"{RT}/connectors/{{instance_id}}/health/history":
            methods |= route.methods
    assert "PATCH" not in methods and "DELETE" not in methods  # append-only, no mutation route


def test_ac18_failed_transition_emits_the_alert_worthy_event(
    client: TestClient, admin: dict, db_session: Session,
):
    instance = _create_mock_instance(client, admin)
    _drive_to_failed(client, admin, db_session, instance)

    audits = db_session.execute(
        select(AuthorizationAudit).where(
            AuthorizationAudit.event_type == "INTEGRATION_CONNECTOR_STATE_CHANGED",
            AuthorizationAudit.organization_id == uuid.UUID(admin["organization_id"]),
        )
    ).scalars().all()
    failed_events = [
        a for a in audits
        if a.meta and a.meta.get("connector_instance_id") == instance["id"] and a.meta.get("to_state") == "failed"
    ]
    assert len(failed_events) == 1
    assert failed_events[0].meta["severity"] == "CRITICAL"


# --------------------------------------------------------------------------- #
# Scheduler & integrity (AC-19..27)
# --------------------------------------------------------------------------- #
def test_ac19_scheduler_disabled_by_default_and_ondemand_is_deterministic(client: TestClient, admin: dict):
    from app.core.config import settings

    assert settings.CONNECTOR_HEALTH_SCHEDULER_ENABLED is False

    instance = _create_mock_instance(client, admin)
    r1 = client.post(f"{RT}/connectors/{instance['id']}/health/check", headers=admin["headers"]).json()
    r2 = client.post(f"{RT}/connectors/{instance['id']}/health/check", headers=admin["headers"]).json()
    assert r1["result"] == r2["result"] == "HEALTHY"


def test_ac20_scheduler_is_interim_in_process_and_functionally_correct(
    client: TestClient, admin: dict, db_session: Session,
):
    source = Path(scheduler.__file__).read_text(encoding="utf-8")
    assert "INTERIM" in source and "REPLACEABLE" in source
    assert "celery" not in source.lower() and "kombu" not in source.lower()
    assert "asyncio" in source

    instance = _create_mock_instance(client, admin)
    client.post(f"{RT}/connectors/{instance['id']}/activate", headers=admin["headers"])

    checked = scheduler.run_sweep_once()
    assert checked >= 1

    row = db_session.execute(
        select(ConnectorHealthCheck).where(
            ConnectorHealthCheck.connector_instance_id == uuid.UUID(instance["id"]),
            ConnectorHealthCheck.check_type == "SCHEDULED",
        )
    ).scalars().first()
    assert row is not None


def test_ac21_health_check_abc_extension_is_additive(client: TestClient, admin: dict):
    abc_methods = {name for name, _ in inspect.getmembers(Connector, predicate=inspect.isfunction)}
    assert abc_methods == {"describe", "validate_configuration", "health_check"}
    assert "authenticate" not in abc_methods and "execute" not in abc_methods

    # 2.1.1 lifecycle smoke, unmodified behavior
    r = client.post(f"{RT}/connectors", headers=admin["headers"], json={
        "connector_type": "MOCK", "name": f"ABC Smoke {uuid.uuid4().hex[:6]}",
        "configuration": {"endpoint": "https://smoke.internal"},
    })
    assert r.status_code == 201 and r.json()["lifecycle_state"] == "configured"


def test_ac22_no_health_or_registry_vocabulary_leaks_into_runtime():
    runtime_root = Path(__file__).resolve().parents[2] / "app" / "runtime"
    forbidden = ("connector", "ConnectorHealthCheck", "ConnectorRegistry")
    offenders = [
        str(path) for path in runtime_root.rglob("*.py")
        if any(term in path.read_text(encoding="utf-8") for term in forbidden)
    ]
    assert offenders == []


def test_ac23_health_endpoints_enforce_permissions_and_reject_cross_org(
    client: TestClient, admin: dict, other_org_admin: dict, viewer: dict,
):
    instance = _create_mock_instance(client, admin)

    assert client.get(f"{RT}/connectors/{instance['id']}/health", headers=viewer["headers"]).status_code == 403
    assert client.post(f"{RT}/connectors/{instance['id']}/health/check", headers=viewer["headers"]).status_code == 403
    assert client.get(f"{RT}/connectors/{instance['id']}/health/history", headers=viewer["headers"]).status_code == 403

    cross = client.get(f"{RT}/connectors/{instance['id']}/health", headers=other_org_admin["headers"])
    assert cross.status_code == 404
    assert cross.json()["error"]["code"] == "CONNECTOR_NOT_FOUND"


def test_ac27_no_new_todo_or_skip_markers_in_this_phases_files():
    root = Path(__file__).resolve().parents[2] / "app" / "integration"
    markers = ("TODO", "FIXME", "XXX", "HACK:", "NotImplementedError")
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            assert marker not in text, f"{marker} found in {path}"
