"""Phase 2.1.4 tests — Connector SDK.

Grouped exactly as the build prompt's §8 groups its acceptance criteria:
surface (AC-01..04), registration parity & completeness (AC-05..09),
governance inheritance (AC-10..15 — the containment core), testing
utilities (AC-16..18), integrity (AC-19..24 — the suite-level ones,
AC-22/23, are proven by the full-suite run cited in the phase summary, not
duplicated here).

The worked example's own tests, which use *only* the SDK testing harness
(AC-03), live in the separate ``test_connector_sdk_example.py`` — kept
separate specifically so that file's own imports can be inspected in
isolation as proof of AC-03, without this file's broader internal-module
imports (needed to test the platform side of the SDK contract) muddying
that proof."""

from __future__ import annotations

import ast
import inspect
import re
import uuid
from pathlib import Path
from typing import Any, Mapping

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.integration.sdk as sdk
from app.integration.base import Connector
from app.integration.errors import ConnectorDeclarationIncompleteError
from app.integration.registry import ConnectorRegistry
from app.integration.sdk.example.webhook_connector import CONNECTOR_TYPE as EXAMPLE_CONNECTOR_TYPE
from app.integration.sdk.example.webhook_connector import WebhookConnector
from app.integration.sdk.http import GovernedHttpClient
from app.integration.sdk.testing import ConnectorTestHarness
from app.integration.service import _CONNECTOR_TYPES, ConnectorTypeService
from app.integration.types import ConnectorDescriptor, ToolContract
from app.integration.validation import HealthCheckNotImplemented, validate_declaration_complete

RT = "/api/v1/integration"
_INTEGRATION_ROOT = Path(__file__).resolve().parents[2] / "app" / "integration"


# --------------------------------------------------------------------------- #
# Fixture connectors used only to prove completeness enforcement (AC-06..09).
# Deliberately never added to `_CONNECTOR_TYPES` -- each is registered
# directly via `ConnectorTypeService.register`, the same single path a real
# author would use, without touching the shared process-wide dict other
# tests depend on.
# --------------------------------------------------------------------------- #
_COMPLETE_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": True}
_COMPLETE_TOOL = ToolContract(name="noop", description="does nothing", parameters={"type": "object", "properties": {}})


class _CompleteFixture(Connector):
    """A minimal but fully complete declaration -- the baseline every
    "missing one thing" variant below is derived from."""

    connector_type = "SDK_TEST_COMPLETE"

    def describe(self) -> ConnectorDescriptor:
        return ConnectorDescriptor(
            connector_type=self.connector_type, version="1.0.0",
            capabilities={"category": "fixture"}, config_schema=_COMPLETE_SCHEMA,
            auth_requirements={"scheme": "NONE"}, tool_contracts=(_COMPLETE_TOOL,),
        )

    def validate_configuration(self, configuration: Mapping[str, Any]) -> None:
        pass

    def health_check(self, configuration: Mapping[str, Any]) -> bool:
        return True


class _MissingConfigSchema(_CompleteFixture):
    connector_type = "SDK_TEST_MISSING_CONFIG_SCHEMA"

    def describe(self) -> ConnectorDescriptor:
        return dataclass_replace(super().describe(), config_schema={})


class _MissingCapabilities(_CompleteFixture):
    connector_type = "SDK_TEST_MISSING_CAPABILITIES"

    def describe(self) -> ConnectorDescriptor:
        return dataclass_replace(super().describe(), capabilities={})


class _MissingToolContracts(_CompleteFixture):
    connector_type = "SDK_TEST_MISSING_TOOL_CONTRACTS"

    def describe(self) -> ConnectorDescriptor:
        return dataclass_replace(super().describe(), tool_contracts=())


class _MalformedToolContract(_CompleteFixture):
    connector_type = "SDK_TEST_MALFORMED_TOOL_CONTRACT"

    def describe(self) -> ConnectorDescriptor:
        bad_tool = ToolContract(name="broken", description="x", parameters={})  # no "type" key
        return dataclass_replace(super().describe(), tool_contracts=(bad_tool,))


class _MissingAuthScheme(_CompleteFixture):
    connector_type = "SDK_TEST_MISSING_AUTH_SCHEME"

    def describe(self) -> ConnectorDescriptor:
        return dataclass_replace(super().describe(), auth_requirements={})


class _UnregisteredAuthScheme(_CompleteFixture):
    connector_type = "SDK_TEST_UNREGISTERED_AUTH_SCHEME"

    def describe(self) -> ConnectorDescriptor:
        return dataclass_replace(super().describe(), auth_requirements={"scheme": "NOT_A_REAL_SCHEME"})


class _HealthCheckNotImplementedFixture(_CompleteFixture):
    connector_type = "SDK_TEST_HEALTH_CHECK_UNIMPLEMENTED"

    def health_check(self, configuration: Mapping[str, Any]) -> bool:
        raise HealthCheckNotImplemented


class _HealthCheckWrongReturnType(_CompleteFixture):
    connector_type = "SDK_TEST_HEALTH_CHECK_WRONG_RETURN"

    def health_check(self, configuration: Mapping[str, Any]):
        return "not a bool"


class _EverythingMissing(Connector):
    connector_type = "SDK_TEST_EVERYTHING_MISSING"

    def describe(self) -> ConnectorDescriptor:
        return ConnectorDescriptor(connector_type=self.connector_type, version="1.0.0")

    def validate_configuration(self, configuration: Mapping[str, Any]) -> None:
        pass

    def health_check(self, configuration: Mapping[str, Any]) -> bool:
        raise HealthCheckNotImplemented


def dataclass_replace(descriptor: ConnectorDescriptor, **changes) -> ConnectorDescriptor:
    import dataclasses

    return dataclasses.replace(descriptor, **changes)


# --------------------------------------------------------------------------- #
# Surface (AC-01..04)
# --------------------------------------------------------------------------- #
def test_ac01_sdk_reexports_the_author_facing_surface():
    expected = {
        "Connector", "ConnectorDescriptor", "ToolContract", "ConnectorLifecycleState",
        "SUPPORTED_AUTH_SCHEMES", "validate_configuration_schema", "ConnectorConfigInvalidError",
        "GovernedHttpClient", "ConnectorTestHarness", "HealthCheckOutcome",
    }
    assert set(sdk.__all__) == expected
    for name in expected:
        assert hasattr(sdk, name), f"app.integration.sdk is missing {name!r}"
    assert issubclass(sdk.Connector, object)
    assert "API_KEY" in sdk.SUPPORTED_AUTH_SCHEMES and "NONE" in sdk.SUPPORTED_AUTH_SCHEMES


def _imported_app_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
            modules.add(node.module)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app."):
                    modules.add(alias.name)
    return modules


def test_ac02_example_imports_only_from_the_sdk_surface():
    path = Path(inspect.getfile(WebhookConnector))
    modules = _imported_app_modules(path)
    assert modules, "expected the example to import something from app.*"
    for module in modules:
        assert module == "app.integration.sdk" or module.startswith("app.integration.sdk."), (
            f"webhook_connector.py imports {module!r}, which is not part of the SDK surface"
        )
    # Concretely, none of the withheld internals appear.
    forbidden = ("app.integration.base", "app.integration.types", "app.integration.auth",
                 "app.integration.service", "app.integration.registry", "app.runtime")
    for module in modules:
        assert not any(module.startswith(f) for f in forbidden), module


def test_ac04_example_exercises_auth_declaration_tool_contract_and_health_check():
    harness = ConnectorTestHarness(WebhookConnector(resolver=lambda host: ["93.184.216.34"]))
    descriptor = harness.describe()
    assert descriptor.connector_type == EXAMPLE_CONNECTOR_TYPE
    assert descriptor.auth_requirements == {"scheme": "BEARER"}
    assert descriptor.auth_requirements["scheme"] in sdk.SUPPORTED_AUTH_SCHEMES

    contract = harness.tool_contract("send_notification")
    assert contract.parameters["required"] == ["message"]

    outcome = harness.run_health_check({"webhook_url": "https://good.example.com/hook"})
    assert outcome == harness.run_health_check({"webhook_url": "https://good.example.com/hook"})
    assert outcome.reachable is True and outcome.error is None

    unreachable = harness.run_health_check({"webhook_url": "not a url"})
    assert unreachable.reachable is False


# --------------------------------------------------------------------------- #
# Registration parity & completeness (AC-05..09)
# --------------------------------------------------------------------------- #
def test_ac05_sdk_connector_registers_through_the_same_registry_path_no_privileged_route(db_session: Session):
    assert _CONNECTOR_TYPES[EXAMPLE_CONNECTOR_TYPE] is WebhookConnector

    # `ensure_seeded` iterates `_CONNECTOR_TYPES` and calls `.register()`
    # uniformly -- no per-identifier branch exists to grant one entry a
    # different path than another.
    source = inspect.getsource(ConnectorTypeService.ensure_seeded)
    assert "if identifier" not in source and "==" not in source

    registry = ConnectorRegistry(db_session)
    type_row = registry.resolve_type(EXAMPLE_CONNECTOR_TYPE)
    assert type_row.connector_type == EXAMPLE_CONNECTOR_TYPE

    # And the exact same service method a MOCK lookup uses.
    mock_row = ConnectorTypeService(db_session).get_or_404("MOCK")
    example_row = ConnectorTypeService(db_session).get_or_404(EXAMPLE_CONNECTOR_TYPE)
    assert mock_row.connector_type == "MOCK"
    assert example_row.connector_type == EXAMPLE_CONNECTOR_TYPE


def test_ac06_missing_config_schema_fails_registration_with_declaration_incomplete(db_session: Session):
    with pytest.raises(ConnectorDeclarationIncompleteError) as excinfo:
        ConnectorTypeService(db_session).register(_MissingConfigSchema())
    assert excinfo.value.code == "CONNECTOR_DECLARATION_INCOMPLETE"
    assert "config_schema" in str(excinfo.value)


@pytest.mark.parametrize(
    "fixture_cls,expected_substring",
    [
        (_MissingCapabilities, "capabilities"),
        (_MissingToolContracts, "tool_contracts"),
        (_MalformedToolContract, "parameters must be a JSON Schema object"),
        (_MissingAuthScheme, "auth_requirements.scheme"),
        (_UnregisteredAuthScheme, "not a registered authentication scheme"),
        (_HealthCheckNotImplementedFixture, "health_check (not implemented)"),
        (_HealthCheckWrongReturnType, "health_check must return a bool"),
    ],
)
def test_ac07_each_missing_element_fails_registration_with_its_own_specific_reason(
    db_session: Session, fixture_cls, expected_substring,
):
    with pytest.raises(ConnectorDeclarationIncompleteError) as excinfo:
        ConnectorTypeService(db_session).register(fixture_cls())
    message = str(excinfo.value)
    assert expected_substring in message
    # And nothing was ever written for a rejected declaration.
    from sqlalchemy import select

    from app.models.integration import Connector as ConnectorRow

    row = db_session.execute(
        select(ConnectorRow).where(ConnectorRow.connector_type == fixture_cls.connector_type)
    ).scalar_one_or_none()
    assert row is None


def test_ac08_the_complete_example_registers_successfully(db_session: Session):
    row = ConnectorTypeService(db_session).register(_CompleteFixture())
    assert row.connector_type == "SDK_TEST_COMPLETE"
    # Re-registering (idempotent upsert, matching the pre-existing convention).
    same_row = ConnectorTypeService(db_session).register(_CompleteFixture())
    assert same_row.id == row.id


def test_ac09_registration_failure_names_exactly_whats_missing(db_session: Session):
    with pytest.raises(ConnectorDeclarationIncompleteError) as excinfo:
        ConnectorTypeService(db_session).register(_EverythingMissing())
    message = str(excinfo.value)
    for expected in (
        "config_schema", "capabilities", "tool_contracts",
        "auth_requirements.scheme", "health_check (not implemented)",
    ):
        assert expected in message, f"{expected!r} not named in: {message}"


# --------------------------------------------------------------------------- #
# Governance inheritance (AC-10..15) -- the containment core
# --------------------------------------------------------------------------- #
def test_ac10_sdk_surface_exposes_no_raw_outbound_call_method():
    for forbidden_name in ("httpx", "requests", "urllib", "socket", "AuthScheme", "OutboundRequest"):
        assert not hasattr(sdk, forbidden_name), f"app.integration.sdk unexpectedly exposes {forbidden_name!r}"

    # GovernedHttpClient is the sole network-capable export; neither of its
    # public methods accepts a per-call host override -- the allowed set is
    # fixed at construction only.
    for method_name in ("request", "evaluate"):
        params = set(inspect.signature(getattr(GovernedHttpClient, method_name)).parameters)
        assert "allowed_hosts" not in params
        assert "host" not in params


def test_ac11_call_to_an_undeclared_host_is_denied_by_the_inherited_egress_guard():
    client = GovernedHttpClient(allowed_hosts={"good.example.com"})

    # Pure policy check -- no DNS, no socket.
    decision = client.evaluate("https://evil.example.com/steal")
    assert decision.allowed is False
    assert decision.reason == "HOST_NOT_ALLOWLISTED"

    # And the real call path denies identically, before any transport is opened.
    result = client.request("GET", "https://evil.example.com/steal")
    assert result.success is False
    assert result.egress_decision.allowed is False
    assert result.egress_decision.reason == "HOST_NOT_ALLOWLISTED"

    # The declared host, by contrast, passes the policy check (still no
    # real socket opened here -- only `evaluate`, with an injected resolver).
    allowed_decision = client.evaluate("https://good.example.com/ok", resolver=lambda h: ["93.184.216.34"])
    assert allowed_decision.allowed is True


def test_ac12_sdk_surface_exposes_no_credential_access_method():
    for forbidden_name in (
        "ConnectorCredentialService", "AuthScheme", "OutboundRequest",
        "decrypt_secret", "encrypt_secret", "credential_crypto", "token_manager",
    ):
        assert not hasattr(sdk, forbidden_name), f"app.integration.sdk unexpectedly exposes {forbidden_name!r}"

    # And the ABC methods a connector implements are structurally incapable
    # of receiving one -- no parameter beyond `self`/`configuration`.
    for method_name in ("describe", "validate_configuration", "health_check"):
        params = list(inspect.signature(getattr(Connector, method_name)).parameters)
        assert params == ["self"] or params == ["self", "configuration"]
        assert not any("credential" in p.lower() for p in params)


def test_ac13_management_actions_all_require_a_permission_via_the_authorization_gateway(
    client: TestClient, admin: dict, viewer: dict,
):
    """No tool-invocation bridge exists yet (2.2.x) -- there is nothing an
    SDK connector's own code can invoke that isn't already one of
    `app/integration/routes.py`'s existing routes. This test proves those
    routes are the *only* entry point (the SDK offers no route-registration
    mechanism of its own, checked below) and that every one of them is
    gated by `require_permission`, which itself evaluates through
    `AuthorizationGateway.authorize` (app/api/deps.py) -- so 2.2.x's future
    tool bridge inherits this gate for free by simply having no alternate,
    ungated path to add."""
    routes_source = (_INTEGRATION_ROOT / "routes.py").read_text(encoding="utf-8")
    route_handlers = re.findall(r"@router\.\w+\([^)]*\)\ndef (\w+)\(", routes_source)
    assert len(route_handlers) >= 15  # every route from 2.1.1-2.1.3 is still present

    # Every route handler's own signature includes a `require_permission(...)`
    # dependency -- no handler falls through ungated.
    handler_bodies = re.split(r"\n(?=@router\.)", routes_source)
    for handler_source in handler_bodies:
        if not handler_source.strip().startswith("@router."):
            continue
        assert "require_permission(" in handler_source, handler_source.splitlines()[0]

    assert not hasattr(sdk, "APIRouter")
    assert not any("router" in name.lower() for name in sdk.__all__)

    # Concretely, live: an authenticated-but-unpermitted caller is denied.
    r = client.post(f"{RT}/connectors", headers=viewer["headers"],
                    json={"connector_type": EXAMPLE_CONNECTOR_TYPE, "name": "denied"})
    assert r.status_code == 403


def test_ac14_sdk_connector_has_no_method_to_suppress_audit():
    for forbidden_name in ("AuthorizationAuditService", "AuthorizationAuditEvent"):
        assert not hasattr(sdk, forbidden_name), f"app.integration.sdk unexpectedly exposes {forbidden_name!r}"
    # No method on the SDK surface accepts anything resembling an
    # audit-suppression flag.
    for name in sdk.__all__:
        obj = getattr(sdk, name)
        for method_name in dir(obj):
            if method_name.startswith("_"):
                continue
            attr = getattr(obj, method_name, None)
            if not callable(attr):
                continue
            try:
                params = inspect.signature(attr).parameters
            except (TypeError, ValueError):
                continue
            assert not any("audit" in p.lower() for p in params)


def test_ac15_sdk_connector_cannot_reach_another_tenants_instance_config_or_credentials():
    for forbidden_name in (
        "Session", "SessionLocal", "get_db", "ConnectorService", "ConnectorRegistry",
        "ConnectorCredentialService", "ConnectorTypeService",
    ):
        assert not hasattr(sdk, forbidden_name), f"app.integration.sdk unexpectedly exposes {forbidden_name!r}"

    # The ABC methods a connector implements never receive a db session or
    # an organization id -- structurally, not by convention.
    for method_name in ("describe", "validate_configuration", "health_check"):
        params = list(inspect.signature(getattr(Connector, method_name)).parameters)
        assert not any(p in ("db", "session", "organization_id", "org_id") for p in params)


# --------------------------------------------------------------------------- #
# Testing utilities (AC-16..18)
# --------------------------------------------------------------------------- #
def test_ac16_harness_validates_declaration_and_configuration_with_no_live_system():
    harness = ConnectorTestHarness(_CompleteFixture())
    harness.assert_declaration_complete()  # does not raise
    harness.assert_configuration_valid({})

    broken_harness = ConnectorTestHarness(WebhookConnector())
    broken_harness.assert_configuration_valid({"webhook_url": "https://x.example.com/hook"})
    message = broken_harness.assert_configuration_invalid({})
    assert "webhook_url" in message

    with pytest.raises(ConnectorDeclarationIncompleteError):
        ConnectorTestHarness(_MissingCapabilities()).assert_declaration_complete()


def test_ac17_harness_exercises_health_check_against_a_synthetic_result():
    class _RaisingHealthCheck(_CompleteFixture):
        def health_check(self, configuration: Mapping[str, Any]) -> bool:
            raise RuntimeError("boom")

    harness = ConnectorTestHarness(_RaisingHealthCheck())
    outcome = harness.run_health_check({})
    assert outcome.reachable is None
    assert outcome.error == "boom"

    ok_harness = ConnectorTestHarness(_CompleteFixture())
    assert ok_harness.run_health_check({}).reachable is True


def test_ac18_harness_exercises_tool_contract_shape_without_a_live_call():
    harness = ConnectorTestHarness(WebhookConnector())
    contract = harness.tool_contract("send_notification")
    assert contract.description
    assert contract.parameters["type"] == "object"
    with pytest.raises(AssertionError):
        harness.tool_contract("does-not-exist")


# --------------------------------------------------------------------------- #
# Integrity (AC-19..24)
# --------------------------------------------------------------------------- #
def test_ac19_mock_connectors_unchanged(db_session: Session):
    from app.integration.mock import MockConnector
    from app.integration.mock_authenticated import MockAuthenticatedConnector

    assert MockConnector().describe().auth_requirements == {"scheme": "NONE"}
    assert MockAuthenticatedConnector().describe().auth_requirements == {"scheme": "API_KEY"}
    # Both still pass the new completeness check unchanged (they were
    # already complete declarations -- this is not a new requirement they
    # had to be updated to satisfy).
    validate_declaration_complete(MockConnector())
    validate_declaration_complete(MockAuthenticatedConnector())


def test_ac21_no_migration_was_added():
    """AC-21 — every table this connector touches already exists; **this
    sub-phase adds no migration of its own**.

    **Rewritten in Phase 4.1, and strengthened rather than relaxed.** This
    assertion used to read "the newest migration file is `<name>`" — a snapshot
    of the repository at the moment it was written, which is false the instant
    any later phase adds one and which says nothing at all about Phase 2.1.4.
    It had already been hand-bumped once (see the Phase 3.5 comment it
    replaced) and was about to need a sixth bump, which is the tell: a guard
    that needs editing every time an unrelated phase ships is pinned to the
    wrong thing.

    What it asserts now is the claim itself — **no migration in this repository
    belongs to Phase 2.1.4** — which stays true forever and is strictly
    stronger, because it also catches a Phase 2.1.4 migration inserted
    *before* the head, a case the newest-file check could never have seen."""
    versions_dir = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    revisions = sorted(versions_dir.glob("00*.py"))
    assert revisions, "no migrations found -- the guard would pass vacuously"

    for revision in revisions:
        source = revision.read_text(encoding="utf-8")
        header = source[:source.find("Revision ID")] if "Revision ID" in source else source
        assert "Phase 2.1.4" not in header, (
            f"{revision.name} is a Phase 2.1.4 migration; this sub-phase must add none."
        )


def test_ac24_no_new_todo_fixme_or_skip_markers_in_the_sdk_files():
    markers = ("TODO", "FIXME", "XXX", "HACK:")
    sdk_root = _INTEGRATION_ROOT / "sdk"
    for path in [*sdk_root.rglob("*.py"), _INTEGRATION_ROOT / "validation.py"]:
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            assert marker not in text, f"{marker} found in {path}"
        assert "pytest.mark.skip" not in text and "xfail" not in text
