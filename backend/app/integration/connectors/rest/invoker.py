"""Phase 2.2.1 SRS ACT-INT-FR-100..106 — the REST connector's tool-invocation
bridge.

**The tool bridge, as of 2.1.4, did not exist.** ``ConnectorRegistry.
resolve_instance_for_invocation`` (2.1.3) already resolves a connector
instance to a fail-fast-checked, plain ``ResolvedConnector`` snapshot, and
its own module docstring says outright "2.2.x's tool bridge is expected to
call this method first" — but nothing before this sub-phase ever did;
there was no code anywhere that turned a connector's declared
``ToolContract`` into a real invocation. This module is that bridge, for
the REST connector specifically: given an instance id, a tool (endpoint)
name, and tool arguments, it renders the request, applies authentication,
calls out through the identical SSRF-hardened path every other governed
call in this platform uses, extracts the response, and (for a paginated
endpoint) drives pagination — a REST connector's declared endpoints are
genuinely, testably invocable end to end (build prompt §3: "a REST
connector nobody can invoke proves nothing").

**Deliberately not part of the SDK-surface-only connector package**
(``declaration.py``/``templating.py``/``extraction.py``/``pagination.py``/
``connector.py``) — this module is platform bridge code sitting *above* a
connector, exactly where ``app/integration/health.py`` and ``app/
integration/service.py`` already sit above every ``Connector``
implementation. It may, and does, import the connector registry and the
authentication framework directly; ``RestConnector`` itself never does.

**Not wired into ``ToolGatewayService``/the model-driven tool loop.**
Milestone 1's tool execution is explicitly out of scope for this
sub-phase (build prompt §3/§11) — this bridge is a genuine, complete,
directly callable invocation path in its own right (``invoke_tool``
below), independent of and untouched by the agent execution loop. A
future milestone that wires connector-derived tools into
``tools_snapshot``/``AgentTool`` assignment can call this function (or an
equivalent) from there without this module changing."""

from __future__ import annotations

import json
import uuid
from typing import Any, Mapping
from urllib.parse import urlencode

from sqlalchemy.orm import Session

from app.identity.errors import ErrorCode, IdentityError
from app.integration.auth.base import OutboundRequest
from app.integration.auth.service import ConnectorCredentialService
from app.integration.connectors.rest import declaration, extraction, pagination, templating
from app.integration.connectors.rest.declaration import RestDeclaration, RestEndpoint
from app.integration.connectors.rest.extraction import ResponseExtractionError
from app.integration.connectors.rest.templating import TemplateRenderError
from app.integration.errors import RestEndpointNotDeclaredError, RestExtractionFailedError, RestTemplateInvalidError
from app.integration.registry import ConnectorRegistry
from app.integration.sdk import GovernedHttpClient

_NO_AUTH_SCHEME = "NONE"


def _endpoint_by_name(decl: RestDeclaration, tool_name: str) -> RestEndpoint:
    endpoint = decl.endpoint_by_name(tool_name)
    if endpoint is None:
        raise RestEndpointNotDeclaredError(tool_name)
    return endpoint


def _hostname(url: str) -> str:
    from urllib.parse import urlsplit

    return (urlsplit(url).hostname or "").lower()


def _payload_or_raise(result) -> Any:
    """Translates an ``HttpExecutionResult`` (never itself raised for a
    denial/failure — see ``GovernedHttpClient``'s own docstring) into
    either a parsed JSON payload or the platform error a caller sees.
    Reuses ``TOOL_EGRESS_DENIED`` for an allowlist violation, per the build
    prompt's own instruction not to invent a REST-specific egress code."""
    if not result.egress_decision.allowed:
        raise IdentityError(
            ErrorCode.TOOL_EGRESS_DENIED,
            f"Outbound REST connector request was denied by egress policy: {result.egress_decision.reason}.",
        )
    if not result.success:
        raise RestExtractionFailedError(f"REST endpoint call did not complete: {result.error or result.status}")
    body = result.response_body_redacted
    if body is None:
        return None
    if isinstance(body, (bytes, bytearray)):
        try:
            return json.loads(body.decode("utf-8")) if body else None
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RestExtractionFailedError(f"response body is not valid JSON: {exc}") from exc
    return body


def invoke_endpoint(
    decl: RestDeclaration, tool_name: str, arguments: Mapping[str, Any], *,
    headers: Mapping[str, str] | None = None, resolver=None,
) -> Any:
    """Renders, calls, and extracts one endpoint's result against an
    already-parsed declaration — no database, no credential resolution;
    ``headers`` (if supplied) already carries any applied authentication.
    Split out from ``invoke_tool`` below so a caller that already has a
    resolved declaration and pre-applied auth (this module's own tests)
    doesn't need a live database at all."""
    endpoint = _endpoint_by_name(decl, tool_name)
    try:
        path = templating.render_path(endpoint.path, endpoint.path_params, arguments)
        query = templating.render_query(endpoint.query_params, arguments)
        rendered_headers = templating.render_headers(endpoint.header_params, arguments)
        body = templating.render_body(endpoint.body_fields, arguments)
    except TemplateRenderError as exc:
        raise RestTemplateInvalidError(str(exc)) from exc

    all_headers = {**rendered_headers, **(headers or {})}
    allowed_hosts = {_hostname(decl.base_url)} | decl.additional_allowed_hosts
    local_dev_hosts = allowed_hosts if decl.allow_plaintext_http else frozenset()
    client = GovernedHttpClient(
        allowed_hosts=allowed_hosts, allow_plaintext_http=decl.allow_plaintext_http, local_dev_hosts=local_dev_hosts,
    )

    url = templating.build_request_url(decl.base_url, path, {})

    def _fetch(page_params: Mapping[str, Any]) -> Any:
        merged_query = {**query, **{k: str(v) for k, v in page_params.items() if v is not None}}
        query_string = urlencode(merged_query) if merged_query else None
        result = client.request(
            endpoint.method, url, headers=all_headers, json_body=body, query=query_string, resolver=resolver,
        )
        return _payload_or_raise(result)

    if endpoint.pagination:
        return pagination.run_pagination(endpoint.pagination, _fetch)

    payload = _fetch({})
    try:
        output = extraction.extract_output(payload, endpoint.response_field)
        if endpoint.output_schema:
            extraction.validate_output_schema(output, endpoint.output_schema)
    except ResponseExtractionError as exc:
        raise RestExtractionFailedError(str(exc)) from exc
    return output


def invoke_tool(
    db: Session, organization_id: uuid.UUID, instance_id: uuid.UUID, tool_name: str,
    arguments: Mapping[str, Any], *, resolver=None, transport=None,
) -> Any:
    """The full, database-backed path: fail-fast resolve the instance
    (``ACT-INT-FR-044``, inherited unchanged from the registry), parse its
    declaration, apply its declared ``auth_scheme`` via the existing
    authentication framework (never inside ``RestConnector`` itself), and
    invoke the named endpoint. This is what makes a REST connector's
    declared endpoints genuinely callable end to end (AC-19)."""
    registry = ConnectorRegistry(db)
    resolved = registry.resolve_instance_for_invocation(organization_id, instance_id)
    decl = declaration.parse_declaration(resolved.configuration)

    headers: dict[str, str] = {}
    if decl.auth_scheme != _NO_AUTH_SCHEME:
        instance_row = registry.instances.get_or_404(organization_id, instance_id)
        outbound = ConnectorCredentialService(db).resolve_and_apply_for_scheme(
            instance_row, OutboundRequest(method="GET", url=decl.base_url), decl.auth_scheme, transport=transport,
        )
        headers = dict(outbound.headers)

    return invoke_endpoint(decl, tool_name, arguments, headers=headers, resolver=resolver)
