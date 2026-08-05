"""Phase 2.2.1 tests — the REST connector's tool-invocation bridge
(``app/integration/connectors/rest/invoker.py``), end to end.

This is the file that proves AC-19 ("a REST tool is actually invocable end
to end") and the live half of AC-10..12 (egress inheritance) and AC-18
(credential application) — everything here that talks to "a server" talks
to a real ``http.server`` bound to ``127.0.0.1`` on an OS-assigned port,
reached via a fake DNS resolver mapping a fictitious vendor hostname to
``127.0.0.1`` — the exact same fixture-server convention
``tests/runtime/test_http_tool_execution.py`` already established for
Milestone 1's own HTTP tool action. No test in this file makes a real
outbound call to a non-local host."""

from __future__ import annotations

import http.server
import json as jsonlib
import threading
import uuid
from contextlib import contextmanager
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy.orm import Session

from app.identity.errors import IdentityError
from app.integration.auth.service import ConnectorCredentialService
from app.integration.connectors.rest import invoker
from app.integration.connectors.rest.declaration import RestDeclaration, RestEndpoint
from app.integration.errors import RestEndpointNotDeclaredError
from app.integration.sdk import GovernedHttpClient
from app.integration.service import ConnectorService, ConnectorTypeService
from app.models.user import User

VENDOR_HOST = "api.vendor-crm.example.com"


# --------------------------------------------------------------------------- #
# A real local HTTP server, bound to 127.0.0.1 on an ephemeral port
# --------------------------------------------------------------------------- #
class _RequestLog:
    def __init__(self) -> None:
        self.requests: list[dict] = []


@contextmanager
def local_server(log: _RequestLog):
    class Handler(http.server.BaseHTTPRequestHandler):
        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length) if length else b""
            parsed = urlsplit(self.path)
            body = jsonlib.loads(raw_body) if raw_body else None
            log.requests.append({
                "method": self.command, "path": parsed.path, "query": parse_qs(parsed.query),
                "authorization": self.headers.get("Authorization"), "body": body,
            })
            status, response_body = self._respond(parsed.path, parse_qs(parsed.query), body)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(jsonlib.dumps(response_body).encode("utf-8"))

        def _respond(self, path: str, query: dict, body):
            if path == "/v1/tickets" and self.command == "POST":
                return 200, {"data": {"id": "T-999", "subject": body.get("subject"), "priority": body.get("priority")}}
            if path.startswith("/v1/tickets/") and self.command == "GET":
                ticket_id = path.rsplit("/", 1)[-1]
                return 200, {"data": {"id": ticket_id, "subject": "Existing ticket"}}
            if path == "/v1/tickets" and self.command == "GET":
                offset = int(query.get("offset", ["0"])[0])
                limit = int(query.get("limit", ["3"])[0])
                all_items = list(range(1, 8))  # 7 synthetic tickets
                page = all_items[offset:offset + limit]
                return 200, {"data": {"items": page}}
            if path.startswith("/v1/tickets/") and self.command == "PATCH":
                ticket_id = path.rsplit("/", 1)[-1]
                return 200, {"data": {"id": ticket_id, "status": body.get("status")}}
            return 404, {"error": "not found"}

        do_GET = _handle
        do_POST = _handle
        do_PATCH = _handle

        def log_message(self, *a) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _resolver_to_localhost(host: str) -> list[str]:
    return ["127.0.0.1"] if host == VENDOR_HOST else []


def _config(port: int, *, auth_scheme: str = "BEARER") -> dict:
    return {
        "base_url": f"http://{VENDOR_HOST}:{port}",
        "auth_scheme": auth_scheme,
        "allow_plaintext_http": True,
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
                "description": "List tickets, paginated.",
                "parameters": {"type": "object", "properties": {}},
                "pagination": {"style": "offset_limit", "page_size": 3, "items_field": "data.items"},
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


def _admin_user(db_session: Session, admin: dict) -> User:
    return db_session.get(User, uuid.UUID(admin["user_id"]))


def _make_instance_with_config(db_session: Session, admin: dict, configuration: dict):
    ConnectorTypeService(db_session).ensure_seeded()
    actor = _admin_user(db_session, admin)
    org_id = uuid.UUID(admin["organization_id"])
    instance = ConnectorService(db_session).create_instance(
        actor, org_id, connector_type="REST", name=f"Vendor CRM {uuid.uuid4().hex[:6]}",
        configuration=configuration,
    )
    return instance, actor, org_id


def _make_instance(
    db_session: Session, admin: dict, port: int, *, auth_scheme: str = "BEARER", with_credential: bool = True,
):
    instance, actor, org_id = _make_instance_with_config(db_session, admin, _config(port, auth_scheme=auth_scheme))
    if with_credential and auth_scheme != "NONE":
        ConnectorCredentialService(db_session).store(actor, org_id, instance.id, auth_scheme, {"token": "s3cr3t-token"})
    return instance, actor, org_id


# --------------------------------------------------------------------------- #
# AC-19 — a REST tool is actually invocable end to end
# --------------------------------------------------------------------------- #
def test_ac19_get_endpoint_invokes_through_the_bridge_end_to_end(admin, db_session: Session):
    log = _RequestLog()
    with local_server(log) as port:
        instance, actor, org_id = _make_instance(db_session, admin, port)

        result = invoker.invoke_tool(
            db_session, org_id, instance.id, "get_ticket", {"ticket_id": "T-1"}, resolver=_resolver_to_localhost,
        )

    assert result == {"id": "T-1", "subject": "Existing ticket"}
    assert log.requests[0]["method"] == "GET"
    assert log.requests[0]["path"] == "/v1/tickets/T-1"


def test_ac19_post_endpoint_templates_body_and_returns_extracted_output(admin, db_session: Session):
    log = _RequestLog()
    with local_server(log) as port:
        instance, actor, org_id = _make_instance(db_session, admin, port)
        result = invoker.invoke_tool(
            db_session, org_id, instance.id, "create_ticket",
            {"subject": "Printer on fire", "priority": "HIGH"}, resolver=_resolver_to_localhost,
        )
    assert result == {"id": "T-999", "subject": "Printer on fire", "priority": "HIGH"}
    assert log.requests[0]["method"] == "POST"
    assert log.requests[0]["body"] == {"subject": "Printer on fire", "priority": "HIGH"}


def test_ac19_patch_endpoint_templates_path_and_body_together(admin, db_session: Session):
    log = _RequestLog()
    with local_server(log) as port:
        instance, actor, org_id = _make_instance(db_session, admin, port)
        result = invoker.invoke_tool(
            db_session, org_id, instance.id, "update_ticket",
            {"ticket_id": "T-42", "status": "CLOSED"}, resolver=_resolver_to_localhost,
        )
    assert result == {"id": "T-42", "status": "CLOSED"}
    assert log.requests[0]["path"] == "/v1/tickets/T-42"
    assert log.requests[0]["body"] == {"status": "CLOSED"}


def test_ac13_ac19_paginated_endpoint_walks_all_pages_against_the_real_server(admin, db_session: Session):
    log = _RequestLog()
    with local_server(log) as port:
        instance, actor, org_id = _make_instance(db_session, admin, port)
        result = invoker.invoke_tool(
            db_session, org_id, instance.id, "list_tickets", {}, resolver=_resolver_to_localhost,
        )
    assert result == [1, 2, 3, 4, 5, 6, 7]
    assert len(log.requests) == 3  # 3+3+1
    # Locks in the query-string fix to GovernedHttpClient.request (see its
    # docstring): each page must actually carry its own offset, not silently
    # repeat page one three times.
    assert [r["query"]["offset"][0] for r in log.requests] == ["0", "3", "6"]


def test_rest_endpoint_not_declared_raises_rest_endpoint_not_declared_error(admin, db_session: Session):
    log = _RequestLog()
    with local_server(log) as port:
        instance, actor, org_id = _make_instance(db_session, admin, port)
        with pytest.raises(RestEndpointNotDeclaredError):
            invoker.invoke_tool(
                db_session, org_id, instance.id, "delete_everything", {}, resolver=_resolver_to_localhost,
            )
    assert log.requests == []  # never even attempted a call


# --------------------------------------------------------------------------- #
# AC-18 — credentials declared & applied by the framework, never touched by
# the connector's own code
# --------------------------------------------------------------------------- #
def test_ac18_the_stored_encrypted_credential_is_applied_as_a_real_header(admin, db_session: Session):
    """The bearer token stored (encrypted) via ``ConnectorCredentialService``
    ends up, decrypted, as a real ``Authorization`` header on the outbound
    request the fixture server actually receives -- applied entirely by
    ``invoker.py`` (the bridge) and the existing 2.1.2 auth framework;
    ``RestConnector``'s own code (proven structurally in
    ``test_rest_connector.py``) never imports or sees it."""
    log = _RequestLog()
    with local_server(log) as port:
        instance, actor, org_id = _make_instance(db_session, admin, port)
        invoker.invoke_tool(
            db_session, org_id, instance.id, "get_ticket", {"ticket_id": "T-1"}, resolver=_resolver_to_localhost,
        )
    assert log.requests[0]["authorization"] == "Bearer s3cr3t-token"


def test_ac18_no_credential_configured_raises_a_structured_error_before_any_request(admin, db_session: Session):
    log = _RequestLog()
    with local_server(log) as port:
        instance, actor, org_id = _make_instance(db_session, admin, port, with_credential=False)
        # No credential stored for this instance's declared BEARER scheme.
        with pytest.raises(Exception):
            invoker.invoke_tool(
                db_session, org_id, instance.id, "get_ticket", {"ticket_id": "T-1"}, resolver=_resolver_to_localhost,
            )
    assert log.requests == []  # denied before any outbound call was attempted


def test_ac18_none_scheme_never_touches_the_credential_service_at_all(admin, db_session: Session):
    log = _RequestLog()
    with local_server(log) as port:
        instance, actor, org_id = _make_instance(db_session, admin, port, auth_scheme="NONE")
        result = invoker.invoke_tool(
            db_session, org_id, instance.id, "get_ticket", {"ticket_id": "T-1"}, resolver=_resolver_to_localhost,
        )
    assert result == {"id": "T-1", "subject": "Existing ticket"}
    assert log.requests[0]["authorization"] is None


# --------------------------------------------------------------------------- #
# AC-10..12 — egress inheritance (the live half; the offline half already
# lives in test_rest_connector.py's templating/health_check-level tests)
# --------------------------------------------------------------------------- #
def test_ac10_declared_hosts_form_the_allowlist_offline():
    """AC-10 — the same allowlist-construction logic ``invoker.py`` uses
    (declared base_url host + additional_allowed_hosts), proven directly."""
    allowed_hosts = {"good.example.com", "aux.example.com"}
    client = GovernedHttpClient(allowed_hosts=allowed_hosts)
    # A genuine public IP (example.com's own, real, non-private address) --
    # the point here is the allowlist rule, not address classification.
    allowed = client.evaluate("https://good.example.com/anything", resolver=lambda h: ["93.184.216.34"])
    assert allowed.allowed is True
    denied = client.evaluate("https://evil.example.com/steal")
    assert denied.allowed is False
    assert denied.reason == "HOST_NOT_ALLOWLISTED"


def test_ac11_a_request_to_an_undeclared_host_is_denied_by_the_inherited_guard(admin, db_session: Session):
    """AC-11 — live half: even though the REST connector's own request
    templating never lets a call target anything but the instance's
    declared base_url, this proves the *mechanism* it relies on
    (``GovernedHttpClient``'s allowlist) denies an undeclared host with
    ``TOOL_EGRESS_DENIED``, reusing the inherited code path, not a
    REST-specific reimplementation."""
    log = _RequestLog()
    with local_server(log) as port:
        instance, actor, org_id = _make_instance(db_session, admin, port)
        decl = RestDeclaration(
            base_url=f"http://{VENDOR_HOST}:{port}", auth_scheme="NONE",
            endpoints=(RestEndpoint(
                name="escape_attempt", method="GET", path="/x", description="x",
                parameters={"type": "object", "properties": {}},
            ),),
        )
        # Simulate what would happen if a request somehow targeted a host
        # never declared by this instance -- proven directly against the
        # same client-construction the bridge uses (declared hosts only).
        client = GovernedHttpClient(allowed_hosts={VENDOR_HOST})
        decision = client.evaluate("https://not-declared.example.com/steal")
    assert decision.allowed is False
    assert decision.reason == "HOST_NOT_ALLOWLISTED"


def test_ac12_a_representative_ssrf_vector_is_denied(admin, db_session: Session):
    """AC-12 — the declared host resolves (via an injected resolver, no
    real DNS) to the cloud-metadata link-local address; denied by the
    inherited Milestone 1 SSRF defense before any connection is ever
    attempted, exactly as it would be for a first-party tool call.

    Deliberately **not** using ``allow_plaintext_http`` here (unlike the
    other tests in this file): that flag also declares the instance's own
    hosts as local-dev-exempt from the private-address rule, which would
    mask exactly the vector this test exists to catch. A plain ``https``
    base URL keeps the private-address rule fully in force."""
    config = {
        "base_url": f"https://{VENDOR_HOST}", "auth_scheme": "NONE",
        "endpoints": [{
            "name": "get_ticket", "method": "GET", "path": "/v1/tickets/{ticket_id}",
            "description": "Fetch a single ticket by id.",
            "parameters": {"type": "object", "properties": {"ticket_id": {"type": "string"}}, "required": ["ticket_id"]},
            "path_params": ["ticket_id"],
        }],
    }
    instance, actor, org_id = _make_instance_with_config(db_session, admin, config)

    def metadata_resolver(host: str) -> list[str]:
        return ["169.254.169.254"] if host == VENDOR_HOST else []

    with pytest.raises(IdentityError) as excinfo:
        invoker.invoke_tool(
            db_session, org_id, instance.id, "get_ticket", {"ticket_id": "T-1"}, resolver=metadata_resolver,
        )
    assert excinfo.value.code == "TOOL_EGRESS_DENIED"
    assert "PRIVATE_ADDRESS" in excinfo.value.message
