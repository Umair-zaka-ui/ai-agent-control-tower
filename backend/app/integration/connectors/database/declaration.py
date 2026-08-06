"""Phase 2.2.2 SRS ACT-INT-FR-120, FR-121, FR-122, FR-125 — the database
connector's declaration model.

A database connector *instance*'s ``configuration`` declares: the target
dialect (``POSTGRESQL``/``MYSQL`` — ``SQLSERVER`` is a recognized but
currently driver-pending value, rejected at semantic validation with a
clear message, see ``drivers.py``), host/port/database, a credential
scheme, a read/write posture, connection-pool limits, default row-limit/
timeout caps, and one or more **declared queries**.

Each declared query is fixed, human-authored SQL text — named, reviewed,
with a JSON-Schema parameter contract and named bind-parameter
placeholders (``:name``, SQLAlchemy's dialect-agnostic named-parameter
syntax, translated to each dialect's native placeholder style entirely
inside the driver layer, never here). **The SQL text itself never
originates from, is concatenated with, or is influenced by model output
anywhere in this codebase** — it is exactly what a human wrote into this
declaration at configuration time, the same "declared and trusted, unlike
model output" distinction the build prompt itself draws (§4.3): inspecting
*this* SQL to classify it read/write (``classify_query`` below) is
legitimate precisely because nothing about it ever came from a model.

``CONFIG_SCHEMA`` is the structural (JSON Schema) half of validation,
run by ``DatabaseConnector.validate_configuration`` via the SDK's own
``validate_configuration_schema``. ``parse_declaration`` is the semantic
half: a query's ``:name`` placeholders must exactly match its declared
parameter schema's own property names (the same discipline 2.2.1's own
path-placeholder/``path_params`` check established), duplicate query
names are rejected, and an unsupported/pending dialect is rejected with a
specific message. Both halves raise ``ConnectorConfigInvalidError`` (the
SDK's own error type) — this module never invents its own validation-time
error, mirroring 2.2.1's own ``declaration.py`` precedent exactly.

``classify_query``/``mutating_query_names`` are the read/write
classification 2.2.2's own build prompt requires at configuration time
(``ACT-INT-FR-125``) — they return plain data (a classification string, a
list of names), never raise; ``connector.py`` is what turns "one or more
mutating queries on a read-only instance" into the dedicated
``DbWriteNotPermittedError`` (a deliberate, documented, narrow deviation
from this module's own SDK-surface-only discipline — see that module's
docstring for why it, not this one, is where that exception is raised)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from app.integration.sdk import ConnectorConfigInvalidError, ToolContract

# SQLSERVER is a recognized, schema-accepted value -- rejected at semantic
# validation with a specific "driver-pending" message, not a generic
# "invalid enum value" -- so an author sees exactly why, not a JSON Schema
# stack trace. See drivers.py for the full rationale.
SUPPORTED_DIALECTS = ("POSTGRESQL", "MYSQL")
_PENDING_DIALECTS = ("SQLSERVER",)
_ALL_DECLARABLE_DIALECTS = SUPPORTED_DIALECTS + _PENDING_DIALECTS

_SUPPORTED_AUTH_SCHEMES = ("NONE", "BASIC")
_PARAM_RE = re.compile(r"(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)")

_READ_KEYWORDS = frozenset({"SELECT", "WITH", "SHOW", "EXPLAIN"})
_COMMENT_LINE_RE = re.compile(r"--[^\n]*")
_COMMENT_BLOCK_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_FIRST_WORD_RE = re.compile(r"[a-zA-Z]+")

_QUERY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "description": {"type": "string", "minLength": 1},
        "sql": {"type": "string", "minLength": 1},
        "parameters": {"type": "object"},
        "result_schema": {"type": ["object", "null"]},
        "row_limit": {"type": ["integer", "null"], "minimum": 1},
        "timeout_seconds": {"type": ["number", "null"], "exclusiveMinimum": 0},
    },
    "required": ["name", "description", "sql", "parameters"],
    "additionalProperties": False,
}

CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "dialect": {"type": "string", "enum": list(_ALL_DECLARABLE_DIALECTS)},
        "host": {"type": "string", "minLength": 1},
        "port": {"type": "integer", "minimum": 1, "maximum": 65535},
        "database": {"type": "string", "minLength": 1},
        "auth_scheme": {"type": "string", "enum": list(_SUPPORTED_AUTH_SCHEMES)},
        # ACT-INT-FR-125 -- read-only unless explicitly set false.
        "read_only": {"type": "boolean"},
        # ACT-INT-FR-126 -- per-instance pool limits.
        "pool_size": {"type": "integer", "minimum": 1, "maximum": 50},
        "max_overflow": {"type": "integer", "minimum": 0, "maximum": 50},
        # ACT-INT-FR-124 -- default/max caps, both configurable.
        "default_row_limit": {"type": "integer", "minimum": 1},
        "max_row_limit": {"type": "integer", "minimum": 1},
        "default_timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
        "max_timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
        "queries": {"type": "array", "items": _QUERY_SCHEMA, "minItems": 1},
    },
    "required": ["dialect", "host", "port", "database", "queries"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class DeclaredQuery:
    """One declared, named, parameterized query — the ``ACT-INT-FR-121``
    unit that becomes one distinct ``ToolContract``. ``sql`` is fixed,
    human-authored text; nothing in this codebase ever rewrites,
    concatenates onto, or derives it from anything else."""

    name: str
    description: str
    sql: str
    parameters: Mapping[str, Any]
    classification: str  # "READ" | "WRITE" -- see classify_query()
    result_schema: Mapping[str, Any] | None = None
    row_limit: int | None = None
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        if self.result_schema is not None:
            object.__setattr__(self, "result_schema", MappingProxyType(dict(self.result_schema)))


@dataclass(frozen=True, slots=True)
class DatabaseDeclaration:
    """A fully parsed, validated instance declaration."""

    dialect: str
    host: str
    port: int
    database: str
    queries: tuple[DeclaredQuery, ...]
    auth_scheme: str = "NONE"
    read_only: bool = True
    pool_size: int = 5
    max_overflow: int = 5
    default_row_limit: int = 500
    max_row_limit: int = 5000
    default_timeout_seconds: float = 10.0
    max_timeout_seconds: float = 60.0

    def query_by_name(self, name: str) -> DeclaredQuery | None:
        for query in self.queries:
            if query.name == name:
                return query
        return None

    def effective_row_limit(self, query: DeclaredQuery) -> int:
        return min(query.row_limit or self.default_row_limit, self.max_row_limit)

    def effective_timeout_seconds(self, query: DeclaredQuery) -> float:
        return min(query.timeout_seconds or self.default_timeout_seconds, self.max_timeout_seconds)


def classify_query(sql: str) -> str:
    """``"READ"`` if the declared SQL's first real (non-comment) token is
    one of ``SELECT``/``WITH``/``SHOW``/``EXPLAIN``, else ``"WRITE"`` —
    fail-closed by design: anything not recognizably read-only is treated
    as a write, rather than allow-listing write keywords and risking a
    miss. Comments are stripped first so a value like
    ``"-- SELECT\\nDROP TABLE x"`` cannot masquerade as read-only."""
    stripped = _COMMENT_BLOCK_RE.sub(" ", sql)
    stripped = _COMMENT_LINE_RE.sub(" ", stripped).strip()
    match = _FIRST_WORD_RE.match(stripped)
    first_word = match.group(0).upper() if match else ""
    return "READ" if first_word in _READ_KEYWORDS else "WRITE"


def mutating_query_names(declaration: DatabaseDeclaration) -> list[str]:
    """The declared query names classified ``"WRITE"`` — empty if none.
    Pure data, never raises; ``connector.py`` decides what a non-empty
    result means for a read-only instance (``ACT-INT-FR-125``)."""
    return [query.name for query in declaration.queries if query.classification == "WRITE"]


def _parse_query(raw: Mapping[str, Any]) -> DeclaredQuery:
    name = raw["name"]
    sql = raw["sql"]
    parameters = raw.get("parameters") or {"type": "object", "properties": {}}
    declared_properties = set((parameters.get("properties") or {}).keys())

    placeholders = set(_PARAM_RE.findall(sql))
    if placeholders != declared_properties:
        raise ConnectorConfigInvalidError(
            f"query '{name}' bind-parameter placeholders {sorted(placeholders)} do not match "
            f"its declared 'parameters' properties {sorted(declared_properties)}"
        )

    row_limit = raw.get("row_limit")
    timeout_seconds = raw.get("timeout_seconds")

    return DeclaredQuery(
        name=name, description=raw["description"], sql=sql, parameters=parameters,
        classification=classify_query(sql), result_schema=raw.get("result_schema"),
        row_limit=row_limit, timeout_seconds=timeout_seconds,
    )


def parse_declaration(configuration: Mapping[str, Any]) -> DatabaseDeclaration:
    """Semantic validation, run after ``CONFIG_SCHEMA``'s structural pass
    (``DatabaseConnector.validate_configuration`` does both, in that
    order). Raises ``ConnectorConfigInvalidError`` naming the specific
    problem. Deliberately does **not** reject a read-only instance's
    mutating query here — that is ``ACT-INT-FR-125``'s own, differently-
    coded rejection (``DB_WRITE_NOT_PERMITTED``), raised by
    ``connector.py`` using ``mutating_query_names`` above, not folded into
    this function's generic config-invalid error."""
    dialect = configuration["dialect"]
    if dialect in _PENDING_DIALECTS:
        raise ConnectorConfigInvalidError(
            f"dialect '{dialect}' support is driver-pending (no driver dependency shipped this phase) "
            f"— supported dialects today: {', '.join(SUPPORTED_DIALECTS)}"
        )
    if dialect not in SUPPORTED_DIALECTS:
        raise ConnectorConfigInvalidError(f"dialect '{dialect}' is not a supported database dialect")

    auth_scheme = configuration.get("auth_scheme", "NONE")
    if auth_scheme not in _SUPPORTED_AUTH_SCHEMES:
        raise ConnectorConfigInvalidError(f"auth_scheme '{auth_scheme}' is not supported by the database connector")

    default_row_limit = int(configuration.get("default_row_limit", 500))
    max_row_limit = int(configuration.get("max_row_limit", 5000))
    if default_row_limit > max_row_limit:
        raise ConnectorConfigInvalidError("default_row_limit cannot exceed max_row_limit")

    default_timeout_seconds = float(configuration.get("default_timeout_seconds", 10.0))
    max_timeout_seconds = float(configuration.get("max_timeout_seconds", 60.0))
    if default_timeout_seconds > max_timeout_seconds:
        raise ConnectorConfigInvalidError("default_timeout_seconds cannot exceed max_timeout_seconds")

    queries_raw = configuration.get("queries") or []
    if not queries_raw:
        raise ConnectorConfigInvalidError("at least one query must be declared")

    seen_names: set[str] = set()
    queries: list[DeclaredQuery] = []
    for raw in queries_raw:
        query = _parse_query(raw)
        if query.name in seen_names:
            raise ConnectorConfigInvalidError(f"duplicate query name '{query.name}'")
        seen_names.add(query.name)
        if query.row_limit is not None and query.row_limit > max_row_limit:
            raise ConnectorConfigInvalidError(f"query '{query.name}' row_limit exceeds max_row_limit")
        if query.timeout_seconds is not None and query.timeout_seconds > max_timeout_seconds:
            raise ConnectorConfigInvalidError(f"query '{query.name}' timeout_seconds exceeds max_timeout_seconds")
        queries.append(query)

    return DatabaseDeclaration(
        dialect=dialect, host=configuration["host"], port=int(configuration["port"]),
        database=configuration["database"], queries=tuple(queries), auth_scheme=auth_scheme,
        read_only=bool(configuration.get("read_only", True)),
        pool_size=int(configuration.get("pool_size", 5)), max_overflow=int(configuration.get("max_overflow", 5)),
        default_row_limit=default_row_limit, max_row_limit=max_row_limit,
        default_timeout_seconds=default_timeout_seconds, max_timeout_seconds=max_timeout_seconds,
    )


def tool_contracts_for(configuration: Mapping[str, Any]) -> tuple[ToolContract, ...]:
    """``ACT-INT-FR-121`` — each declared query becomes one distinct
    ``ToolContract``, mirroring 2.2.1's own ``tool_contracts_for``
    exactly. Instance-derived, not something ``DatabaseConnector.
    describe()`` (a type-level, zero-argument call) can produce — see
    ``connector.py``'s module docstring."""
    declaration = parse_declaration(configuration)
    return tuple(
        ToolContract(name=query.name, description=query.description, parameters=query.parameters)
        for query in declaration.queries
    )
