"""Phase 2.2.1 SRS ACT-INT-FR-100, FR-101, FR-102, FR-106 — the REST
connector's declaration model.

A REST connector *instance*'s ``configuration`` is exactly this shape:
``base_url``, ``auth_scheme`` (one of ``app.integration.sdk.
SUPPORTED_AUTH_SCHEMES``), an optional ``additional_allowed_hosts`` list
(egress-allowlist hosts beyond ``base_url``'s own host — a vendor whose
auth token endpoint lives on a different host from its API, for
instance), and one or more ``endpoints``. Each endpoint declares a method,
a path template (``{placeholder}`` tokens), the tool's own argument schema
(``parameters``), which named arguments go where (``path_params``/
``query_params``/``header_params``/``body_fields``), how to extract the
tool's output from the response (``response_field``, dotted path; absent
means "the whole body"), an optional ``output_schema``, and an optional
``pagination`` declaration.

``CONFIG_SCHEMA`` is the structural (JSON Schema) half of validation, run
by ``RestConnector.validate_configuration`` via the SDK's own
``validate_configuration_schema`` before anything here ever sees the
configuration. ``parse_declaration`` is the semantic half — the checks a
JSON Schema alone cannot express (a path's ``{placeholder}`` tokens must
exactly match its declared ``path_params``; every argument name referenced
by ``query_params``/``header_params``/``body_fields``/``path_params`` must
be one this endpoint's own ``parameters`` actually declares; an
``auth_scheme`` must be one this platform actually registers). Both halves
raise ``ConnectorConfigInvalidError`` (the SDK's own error type) — this
module never invents a validation-time error of its own, since instance
configuration validity is exactly what that error already means."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlsplit

from app.integration.sdk import SUPPORTED_AUTH_SCHEMES, ConnectorConfigInvalidError, ToolContract

_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
_PAGINATION_STYLES = ("offset_limit", "page_number", "cursor")
_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_NO_AUTH_SCHEME = "NONE"

_ENDPOINT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "method": {"type": "string", "enum": list(_METHODS)},
        "path": {"type": "string", "minLength": 1},
        "description": {"type": "string", "minLength": 1},
        "parameters": {"type": "object"},
        "path_params": {"type": "array", "items": {"type": "string"}},
        "query_params": {"type": "object", "additionalProperties": {"type": "string"}},
        "header_params": {"type": "object", "additionalProperties": {"type": "string"}},
        "body_fields": {"type": "array", "items": {"type": "string"}},
        "response_field": {"type": ["string", "null"]},
        "output_schema": {"type": ["object", "null"]},
        "pagination": {
            "type": ["object", "null"],
            "properties": {
                "style": {"type": "string", "enum": list(_PAGINATION_STYLES)},
                "page_size": {"type": "integer", "minimum": 1},
                "max_pages": {"type": "integer", "minimum": 1},
                "items_field": {"type": "string"},
                "cursor_field": {"type": "string"},
                "start_page": {"type": "integer", "minimum": 0},
                "start_offset": {"type": "integer", "minimum": 0},
            },
            "required": ["style"],
            "additionalProperties": True,
        },
    },
    "required": ["name", "method", "path", "description", "parameters"],
    "additionalProperties": False,
}

CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "base_url": {"type": "string", "minLength": 1},
        "auth_scheme": {"type": "string", "minLength": 1},
        "additional_allowed_hosts": {"type": "array", "items": {"type": "string"}},
        # Mirrors the exact escape hatch Milestone 1's own HTTP tool
        # `http_config` already carries (`allow_plaintext_http`) -- an
        # internal/dev/staging vendor API reachable only over plain HTTP.
        # When set, every one of this instance's own declared hosts
        # (never a wider set) is treated as a declared local-dev host, so
        # opting in never widens reachability beyond what was already
        # declared -- only *how* it may be reached.
        "allow_plaintext_http": {"type": "boolean"},
        "endpoints": {"type": "array", "items": _ENDPOINT_SCHEMA, "minItems": 1},
    },
    "required": ["base_url", "auth_scheme", "endpoints"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class RestEndpoint:
    """One declared endpoint — the ``ACT-INT-FR-102`` unit that becomes one
    distinct ``ToolContract``. Immutable, mirroring every other
    connector-neutral declaration type in this codebase."""

    name: str
    method: str
    path: str
    description: str
    parameters: Mapping[str, Any]
    path_params: tuple[str, ...] = ()
    query_params: Mapping[str, str] = field(default_factory=dict)
    header_params: Mapping[str, str] = field(default_factory=dict)
    body_fields: tuple[str, ...] = ()
    response_field: str | None = None
    output_schema: Mapping[str, Any] | None = None
    pagination: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        object.__setattr__(self, "path_params", tuple(self.path_params))
        object.__setattr__(self, "query_params", MappingProxyType(dict(self.query_params)))
        object.__setattr__(self, "header_params", MappingProxyType(dict(self.header_params)))
        object.__setattr__(self, "body_fields", tuple(self.body_fields))
        if self.pagination is not None:
            object.__setattr__(self, "pagination", MappingProxyType(dict(self.pagination)))
        if self.output_schema is not None:
            object.__setattr__(self, "output_schema", MappingProxyType(dict(self.output_schema)))


@dataclass(frozen=True, slots=True)
class RestDeclaration:
    """A fully parsed, validated instance declaration."""

    base_url: str
    auth_scheme: str
    endpoints: tuple[RestEndpoint, ...]
    additional_allowed_hosts: frozenset[str] = frozenset()
    allow_plaintext_http: bool = False

    def endpoint_by_name(self, name: str) -> RestEndpoint | None:
        for endpoint in self.endpoints:
            if endpoint.name == name:
                return endpoint
        return None


def _parse_endpoint(raw: Mapping[str, Any]) -> RestEndpoint:
    name = raw["name"]
    parameters = raw.get("parameters") or {"type": "object", "properties": {}}
    declared_properties = set((parameters.get("properties") or {}).keys())

    path_params = tuple(raw.get("path_params") or ())
    query_params = dict(raw.get("query_params") or {})
    header_params = dict(raw.get("header_params") or {})
    body_fields = tuple(raw.get("body_fields") or ())

    referenced = set(path_params) | set(query_params.values()) | set(header_params.values()) | set(body_fields)
    unknown = referenced - declared_properties
    if unknown:
        raise ConnectorConfigInvalidError(
            f"endpoint '{name}' references argument(s) {sorted(unknown)} not declared in its own 'parameters'"
        )

    placeholders = set(_PLACEHOLDER_RE.findall(raw["path"]))
    if placeholders != set(path_params):
        raise ConnectorConfigInvalidError(
            f"endpoint '{name}' path placeholders {sorted(placeholders)} do not match "
            f"its declared path_params {sorted(path_params)}"
        )

    pagination = raw.get("pagination")
    if pagination is not None and pagination.get("style") not in _PAGINATION_STYLES:
        raise ConnectorConfigInvalidError(
            f"endpoint '{name}' declares an unsupported pagination style {pagination.get('style')!r}"
        )

    return RestEndpoint(
        name=name, method=raw["method"], path=raw["path"], description=raw["description"],
        parameters=parameters, path_params=path_params, query_params=query_params,
        header_params=header_params, body_fields=body_fields,
        response_field=raw.get("response_field"), output_schema=raw.get("output_schema"),
        pagination=pagination,
    )


def parse_declaration(configuration: Mapping[str, Any]) -> RestDeclaration:
    """Semantic validation, run after ``CONFIG_SCHEMA``'s structural pass
    (``RestConnector.validate_configuration`` does both, in that order —
    AC-04). Raises ``ConnectorConfigInvalidError`` naming the specific
    problem; never silently accepts a self-contradictory declaration."""
    base_url = configuration["base_url"]
    parsed = urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ConnectorConfigInvalidError(f"base_url '{base_url}' must be an absolute http(s) URL")

    auth_scheme = configuration["auth_scheme"]
    if auth_scheme not in SUPPORTED_AUTH_SCHEMES:
        raise ConnectorConfigInvalidError(
            f"auth_scheme '{auth_scheme}' is not a supported authentication scheme"
        )

    additional_hosts = frozenset(h.lower() for h in (configuration.get("additional_allowed_hosts") or ()))

    endpoints_raw = configuration.get("endpoints") or []
    if not endpoints_raw:
        raise ConnectorConfigInvalidError("at least one endpoint must be declared")

    seen_names: set[str] = set()
    endpoints: list[RestEndpoint] = []
    for raw in endpoints_raw:
        endpoint = _parse_endpoint(raw)
        if endpoint.name in seen_names:
            raise ConnectorConfigInvalidError(f"duplicate endpoint name '{endpoint.name}'")
        seen_names.add(endpoint.name)
        endpoints.append(endpoint)

    return RestDeclaration(
        base_url=base_url, auth_scheme=auth_scheme, endpoints=tuple(endpoints),
        additional_allowed_hosts=additional_hosts,
        allow_plaintext_http=bool(configuration.get("allow_plaintext_http", False)),
    )


def tool_contracts_for(configuration: Mapping[str, Any]) -> tuple[ToolContract, ...]:
    """``ACT-INT-FR-102`` — each declared endpoint becomes one distinct
    ``ToolContract``. This is *instance*-derived, not something
    ``RestConnector.describe()`` (a type-level, zero-argument call) can
    produce — see ``connector.py``'s module docstring for why the type's
    own ``describe()`` carries only a structural placeholder contract, and
    this function is the real mechanism ``ACT-INT-FR-102`` describes."""
    declaration = parse_declaration(configuration)
    return tuple(
        ToolContract(name=endpoint.name, description=endpoint.description, parameters=endpoint.parameters)
        for endpoint in declaration.endpoints
    )
