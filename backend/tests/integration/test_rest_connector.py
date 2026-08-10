"""Phase 2.2.1 tests — Generic REST Connector.

Grouped exactly as the build prompt's §8 groups its acceptance criteria:
declaration & tool contracts (AC-01..04), templating & extraction
(AC-05..09), egress inheritance (AC-10..12 — see
``test_rest_connector_invocation.py`` for the live half of these, since a
real ``GovernedHttpClient`` is only actually built by the invocation
bridge), pagination (AC-13..14), SDK-surface & integrity (AC-15..25 — the
suite-level ones, AC-23/24, are reported from the full-suite run cited in
the phase summary, not duplicated here; AC-19, the end-to-end invocation
proof, lives in ``test_rest_connector_invocation.py``)."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.integration.connectors.rest import declaration, extraction, pagination, templating
from app.integration.connectors.rest.connector import CONNECTOR_TYPE, CONNECTOR_VERSION, RestConnector
from app.integration.connectors.rest.declaration import parse_declaration, tool_contracts_for
from app.integration.connectors.rest.extraction import ResponseExtractionError
from app.integration.connectors.rest.templating import TemplateRenderError
from app.integration.errors import ConnectorConfigInvalidError
from app.integration.mock import MockConnector
from app.integration.mock_authenticated import MockAuthenticatedConnector
from app.integration.sdk import ConnectorTestHarness
from app.integration.sdk.example.webhook_connector import WebhookConnector
from app.integration.service import _CONNECTOR_TYPES, ConnectorTypeService
from app.models.integration import Connector as ConnectorRow

_REST_PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "app" / "integration" / "connectors" / "rest"
_CONNECTOR_ONLY_FILES = ("declaration.py", "templating.py", "extraction.py", "pagination.py", "connector.py")

# A realistic, multi-endpoint, vendor-like declaration (a plausible support-
# ticketing CRM API) -- the concrete ACT-INT-FR-106 proof: configured
# entirely as data, no code, and exercised below against fixtured responses
# (never a live call).
VENDOR_DECLARATION: dict[str, Any] = {
    "base_url": "https://api.vendor-crm.example.com",
    "auth_scheme": "BEARER",
    "additional_allowed_hosts": ["auth.vendor-crm.example.com"],
    "endpoints": [
        {
            "name": "create_ticket", "method": "POST", "path": "/v1/tickets",
            "description": "Create a new support ticket.",
            "parameters": {
                "type": "object",
                "properties": {"subject": {"type": "string"}, "priority": {"type": "string"}},
                "required": ["subject"],
            },
            "body_fields": ["subject", "priority"],
            "response_field": "data",
        },
        {
            "name": "get_ticket", "method": "GET", "path": "/v1/tickets/{ticket_id}",
            "description": "Fetch a single ticket by id.",
            "parameters": {
                "type": "object", "properties": {"ticket_id": {"type": "string"}}, "required": ["ticket_id"],
            },
            "path_params": ["ticket_id"],
            "response_field": "data",
        },
        {
            "name": "list_tickets", "method": "GET", "path": "/v1/tickets",
            "description": "List tickets, optionally filtered by status.",
            "parameters": {"type": "object", "properties": {"status": {"type": "string"}}},
            "query_params": {"status": "status"},
            "pagination": {"style": "offset_limit", "page_size": 25, "items_field": "data.items"},
        },
        {
            "name": "update_ticket", "method": "PATCH", "path": "/v1/tickets/{ticket_id}",
            "description": "Update a ticket's status.",
            "parameters": {
                "type": "object",
                "properties": {"ticket_id": {"type": "string"}, "status": {"type": "string"}},
                "required": ["ticket_id", "status"],
            },
            "path_params": ["ticket_id"], "body_fields": ["status"],
            "response_field": "data",
        },
    ],
}


# --------------------------------------------------------------------------- #
# Declaration & tool contracts (AC-01..04)
# --------------------------------------------------------------------------- #
def test_ac01_instance_configured_entirely_by_declaration_no_code():
    """AC-01 — validation succeeds against a pure-data declaration; nothing
    about it required a Python subclass or code of any kind."""
    RestConnector().validate_configuration(VENDOR_DECLARATION)


def test_ac02_each_declared_endpoint_produces_a_distinct_tool_contract():
    """AC-02."""
    contracts = tool_contracts_for(VENDOR_DECLARATION)
    names = [c.name for c in contracts]
    assert names == ["create_ticket", "get_ticket", "list_tickets", "update_ticket"]
    for contract, endpoint in zip(contracts, VENDOR_DECLARATION["endpoints"]):
        assert contract.description == endpoint["description"]
        assert contract.parameters == endpoint["parameters"]


def test_ac03_the_vendor_like_declaration_is_the_fr106_proof():
    """AC-03 — a realistic, multi-endpoint vendor API (create/get/list-
    paginated/update) configures without code and produces exactly the
    tool contracts FR-106 asks for."""
    harness = ConnectorTestHarness(RestConnector())
    harness.assert_configuration_valid(VENDOR_DECLARATION)
    contracts = tool_contracts_for(VENDOR_DECLARATION)
    assert len(contracts) == 4
    assert {c.name for c in contracts} == {"create_ticket", "get_ticket", "list_tickets", "update_ticket"}


@pytest.mark.parametrize("broken, expected_fragment", [
    ({**VENDOR_DECLARATION, "base_url": "not-a-url"}, "base_url"),
    ({**VENDOR_DECLARATION, "auth_scheme": "NOT_A_REAL_SCHEME"}, "auth_scheme"),
    ({**VENDOR_DECLARATION, "endpoints": []}, "at least one endpoint"),
    (
        {**VENDOR_DECLARATION, "endpoints": [
            {**VENDOR_DECLARATION["endpoints"][1], "path": "/v1/tickets/{ticket_id}/{extra}"},
        ]},
        "placeholders",
    ),
    (
        {**VENDOR_DECLARATION, "endpoints": [
            {**VENDOR_DECLARATION["endpoints"][0], "body_fields": ["not_a_declared_arg"]},
        ]},
        "not declared",
    ),
    (
        {**VENDOR_DECLARATION, "endpoints": [
            VENDOR_DECLARATION["endpoints"][0], VENDOR_DECLARATION["endpoints"][0],
        ]},
        "duplicate",
    ),
])
def test_ac04_an_invalid_declaration_is_rejected_with_a_specific_error(broken, expected_fragment):
    """AC-04."""
    with pytest.raises(ConnectorConfigInvalidError) as excinfo:
        RestConnector().validate_configuration(broken)
    assert expected_fragment.split()[0] in str(excinfo.value) or expected_fragment in str(excinfo.value)


def test_ac04_missing_required_top_level_keys_rejected_at_schema_level():
    """AC-04 — the structural (JSON Schema) half rejects a declaration
    missing a required top-level key before semantic parsing ever runs."""
    with pytest.raises(ConnectorConfigInvalidError):
        RestConnector().validate_configuration({"base_url": "https://api.example.com"})


# --------------------------------------------------------------------------- #
# Templating & extraction (AC-05..09)
# --------------------------------------------------------------------------- #
def test_ac05_arguments_template_into_path_query_header_and_body():
    """AC-05."""
    path = templating.render_path("/v1/tickets/{ticket_id}", ("ticket_id",), {"ticket_id": "T-100"})
    assert path == "/v1/tickets/T-100"

    query = templating.render_query({"status": "status_filter"}, {"status_filter": "open"})
    assert query == {"status": "open"}

    headers = templating.render_headers({"X-Request-Id": "request_id"}, {"request_id": "abc-123"})
    assert headers == {"X-Request-Id": "abc-123"}

    body = templating.render_body(("subject", "priority"), {"subject": "Printer on fire", "priority": "HIGH"})
    assert body == {"subject": "Printer on fire", "priority": "HIGH"}

    url = templating.build_request_url("https://api.example.com", path, query)
    assert url == "https://api.example.com/v1/tickets/T-100?status=open"


def test_ac06_a_path_argument_cannot_escape_the_declared_endpoint():
    """AC-06 — the concrete adversarial value from the build prompt."""
    rendered = templating.render_path("/records/{record_id}", ("record_id",), {"record_id": "123/../admin"})
    assert rendered == "/records/123%2F..%2Fadmin"
    assert "/admin" not in rendered
    url = templating.build_request_url("https://api.example.com", rendered, {})
    assert url == "https://api.example.com/records/123%2F..%2Fadmin"
    # scheme's "//" (2) + "/records" (1) + the templated segment's own
    # leading "/" (1) == 4; the encoded value contributes zero *literal*
    # slashes of its own -- no escaped path segment reaches the URL.
    assert url.count("/") == 4


@pytest.mark.parametrize("value", ["evil\r\nX-Injected: 1", "evil\nSet-Cookie: a=b", "null\x00byte"])
def test_ac07_argument_values_cannot_inject_headers_or_alter_request_structure(value):
    """AC-07."""
    with pytest.raises(TemplateRenderError):
        templating.render_headers({"X-Custom": "custom_value"}, {"custom_value": value})
    with pytest.raises(TemplateRenderError):
        templating.render_query({"q": "q_value"}, {"q_value": value})


def test_ac07_path_argument_missing_raises_template_error():
    with pytest.raises(TemplateRenderError):
        templating.render_path("/tickets/{ticket_id}", ("ticket_id",), {})


def test_ac08_response_extraction_maps_response_to_tool_output():
    """AC-08."""
    payload = {"data": {"id": "T-1", "subject": "Hi"}, "meta": {"trace": "x"}}
    assert extraction.extract_output(payload, "data") == {"id": "T-1", "subject": "Hi"}
    assert extraction.extract_output(payload, None) == payload
    assert extraction.extract_output(payload, "data.id") == "T-1"

    with pytest.raises(ResponseExtractionError):
        extraction.extract_output(payload, "data.missing_field")


def test_ac09_output_schema_validation_applies_where_declared():
    """AC-09 — Milestone 1's own schema-validation library (``jsonschema``),
    applied here exactly as ``base.py``/``runtime/services.py`` already do."""
    schema = {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}
    extraction.validate_output_schema({"id": "T-1"}, schema)  # does not raise
    with pytest.raises(ResponseExtractionError):
        extraction.validate_output_schema({"id": 123}, schema)
    with pytest.raises(ResponseExtractionError):
        extraction.validate_output_schema({}, schema)


# --------------------------------------------------------------------------- #
# Pagination (AC-13..14) — pure, no HTTP at all
# --------------------------------------------------------------------------- #
def test_ac13_offset_limit_pagination_walks_pages_to_the_short_final_one():
    pages = [
        {"items": [1, 2]}, {"items": [3, 4]}, {"items": [5]},
    ]
    calls: list[dict] = []

    def fetch_page(params):
        calls.append(dict(params))
        return pages[len(calls) - 1]

    result = pagination.run_pagination({"style": "offset_limit", "page_size": 2, "items_field": "items"}, fetch_page)
    assert result == [1, 2, 3, 4, 5]
    assert calls == [{"offset": 0, "limit": 2}, {"offset": 2, "limit": 2}, {"offset": 4, "limit": 2}]


def test_ac13_page_number_pagination_walks_pages_to_the_short_final_one():
    pages = [{"items": ["a", "b"]}, {"items": ["c"]}]
    calls: list[dict] = []

    def fetch_page(params):
        calls.append(dict(params))
        return pages[len(calls) - 1]

    result = pagination.run_pagination({"style": "page_number", "page_size": 2, "items_field": "items"}, fetch_page)
    assert result == ["a", "b", "c"]
    assert calls == [{"page": 1, "page_size": 2}, {"page": 2, "page_size": 2}]


def test_ac13_cursor_pagination_stops_when_no_next_cursor():
    pages = [
        {"items": [1, 2], "next_cursor": "tok-2"},
        {"items": [3, 4], "next_cursor": "tok-3"},
        {"items": [5], "next_cursor": None},
    ]
    calls: list[dict] = []

    def fetch_page(params):
        calls.append(dict(params))
        return pages[len(calls) - 1]

    result = pagination.run_pagination({"style": "cursor", "items_field": "items"}, fetch_page)
    assert result == [1, 2, 3, 4, 5]
    assert calls == [{}, {"cursor": "tok-2"}, {"cursor": "tok-3"}]


def test_ac14_pagination_is_bounded_even_when_the_server_never_stops():
    """AC-14 — a misbehaving/malicious server that always returns a full
    page (offset/limit, page_number) cannot force an unbounded fetch: the
    declared ``max_pages`` caps it, and a hard ceiling caps even a
    declaration that tries to ask for more than that."""
    calls = {"count": 0}

    def never_ending_full_page(params):
        calls["count"] += 1
        return {"items": [1, 2]}  # always a "full" page -- never signals "done"

    result = pagination.run_pagination(
        {"style": "offset_limit", "page_size": 2, "max_pages": 5, "items_field": "items"},
        never_ending_full_page,
    )
    assert calls["count"] == 5
    assert len(result) == 10

    calls["count"] = 0
    pagination.run_pagination(
        {"style": "page_number", "page_size": 2, "max_pages": 10_000, "items_field": "items"},
        never_ending_full_page,
    )
    assert calls["count"] == pagination._HARD_MAX_PAGES  # the declared cap is itself capped


# --------------------------------------------------------------------------- #
# SDK-surface & integrity (AC-15..25)
# --------------------------------------------------------------------------- #
def _app_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app."):
                    modules.add(alias.name)
    return modules


def test_ac15_the_connector_package_imports_only_from_the_sdk_surface_or_itself():
    """AC-15 — ``declaration.py``/``templating.py``/``extraction.py``/
    ``pagination.py``/``connector.py`` (the connector itself, as opposed to
    ``invoker.py``, the platform bridge sitting above it) import only
    ``app.integration.sdk`` or their own sibling modules."""
    for filename in _CONNECTOR_ONLY_FILES:
        modules = _app_imports(_REST_PACKAGE_ROOT / filename)
        for module in modules:
            assert module == "app.integration.sdk" or module.startswith("app.integration.sdk.") \
                or module.startswith("app.integration.connectors.rest"), (
                f"{filename} imports {module!r}, reaching past the SDK surface"
            )


def test_ac16_governedhttpclient_is_the_only_outbound_mechanism():
    """AC-16 — no file in the REST connector package (including the
    bridge, ``invoker.py``) imports a raw HTTP client directly."""
    forbidden = ("httpx", "requests", "urllib.request", "http.client", "socket")
    for filename in list(_CONNECTOR_ONLY_FILES) + ["invoker.py", "__init__.py"]:
        text = (_REST_PACKAGE_ROOT / filename).read_text(encoding="utf-8")
        tree = ast.parse(text)
        top_level_imports = {
            alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
        } | {
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
        }
        for name in forbidden:
            assert name not in top_level_imports, f"{filename} imports forbidden raw transport {name!r}"


def test_ac17_rest_connector_registers_through_the_identical_shared_path(db_session):
    """AC-17 — registration parity: ``RestConnector`` sits in the exact
    same ``_CONNECTOR_TYPES`` dict as ``MOCK``/``MOCK_AUTH``/
    ``SDK_EXAMPLE_WEBHOOK``, flowing through ``ensure_seeded``/``register``
    with no per-identifier branching (2.1.4's own AC-05 test already
    proves ``ensure_seeded`` itself has none; this proves REST is actually
    one of the dict's entries, not a parallel mechanism)."""
    assert _CONNECTOR_TYPES["REST"] is RestConnector
    service = ConnectorTypeService(db_session)
    service.ensure_seeded()
    row = db_session.execute(
        select(ConnectorRow).where(ConnectorRow.connector_type == CONNECTOR_TYPE, ConnectorRow.version == CONNECTOR_VERSION)
    ).scalar_one()
    assert row.connector_type == "REST"
    # Idempotent re-seed does not duplicate or edit the row (ACT-INT-FR-008).
    service.ensure_seeded()
    count = db_session.execute(
        select(ConnectorRow).where(ConnectorRow.connector_type == "REST")
    ).scalars().all()
    assert len(count) == 1


def test_ac18_rest_connector_itself_never_imports_the_credential_or_auth_framework():
    """AC-18 (the structural half — the live half, proving a real stored
    credential's header actually appears on the outbound request without
    ``RestConnector``'s own code ever touching it, is in
    ``test_rest_connector_invocation.py``). Neither ``connector.py`` nor
    any of its SDK-surface siblings imports ``app.integration.auth``,
    ``ConnectorCredentialService``, or ``credential_crypto`` — only
    ``invoker.py`` (the bridge) does."""
    for filename in _CONNECTOR_ONLY_FILES:
        modules = _app_imports(_REST_PACKAGE_ROOT / filename)
        assert not any(m.startswith("app.integration.auth") for m in modules), (
            f"{filename} reaches into the authentication framework directly"
        )
        assert not any("credential" in m.lower() for m in modules)
    bridge_modules = _app_imports(_REST_PACKAGE_ROOT / "invoker.py")
    assert any(m.startswith("app.integration.auth") for m in bridge_modules)


def test_ac20_2_1_x_framework_connectors_still_describe_and_validate_unchanged():
    """AC-20 — MOCK/MOCK_AUTH/WEBHOOK are untouched by this sub-phase."""
    assert MockConnector().describe().auth_requirements == {"scheme": "NONE"}
    MockConnector().validate_configuration({"endpoint": "https://mock.internal"})
    assert MockAuthenticatedConnector().describe().auth_requirements == {"scheme": "API_KEY"}
    assert WebhookConnector().describe().connector_type == "SDK_EXAMPLE_WEBHOOK"


def test_ac22_migration_head_unchanged_no_new_migration_needed():
    """AC-22 — every table the REST connector touches
    (``connectors``/``connector_instances``/``connector_credentials``)
    already exists; this sub-phase adds none, mirroring 2.1.4's own
    "no migration" finding and its own equivalent test."""
    migrations_dir = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    versions = sorted(p.name for p in migrations_dir.glob("00*.py"))
    # Updated Phase 3.1: a genuinely new migration landed for the deployment
    # lifecycle (0037) -- this assertion's own intent ("no migration crept
    # in that this connector's own tests didn't account for") is preserved
    # by pointing at the new, correct head.
    assert versions[-1] == "0037_deployment_lifecycle.py"


def test_ac25_no_stub_markers_in_this_phases_new_files():
    """AC-25."""
    forbidden = ("TODO", "FIXME", "XXX", "HACK", "NotImplementedError", "pytest.skip", "xfail")
    for filename in list(_CONNECTOR_ONLY_FILES) + ["invoker.py", "__init__.py"]:
        text = (_REST_PACKAGE_ROOT / filename).read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text, f"{filename} contains forbidden marker {marker!r}"


def test_rest_connector_declares_no_extra_ctor_parameters_beyond_the_test_only_resolver_hook():
    """Structural sanity check mirroring 2.1.4's own governance-inheritance
    style: ``RestConnector``'s ABC-required methods take no db/session/
    organization_id/credential parameter."""
    for method_name in ("describe", "validate_configuration", "health_check"):
        params = list(inspect.signature(getattr(RestConnector, method_name)).parameters)
        assert all(p in ("self", "configuration") for p in params)
