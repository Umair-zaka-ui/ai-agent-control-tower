"""Phase 2.2.2 SRS ACT-INT-FR-120, FR-126, FR-127 — the dialect abstraction.

One small interface over PostgreSQL and MySQL — connection-URL
construction and a per-instance connection-pool cache — built on
SQLAlchemy Core (already a first-class dependency of this codebase, used
for the platform's own database, not a new toolkit introduced for this
connector). Vendor-specific bind-parameter placeholder styles
(``%(name)s`` for psycopg2, ``%(name)s`` for PyMySQL, ``?`` for a future
pyodbc/SQL Server driver) are translated from the declaration's uniform
``:name`` syntax entirely inside SQLAlchemy's own dialect layer — this
module never sees, and never needs to see, a vendor-specific placeholder
at all. Adding a fourth dialect is one new entry in ``_DIALECT_DRIVERNAME``
plus whatever DBAPI package that dialect needs; nothing else changes.

**SQL Server is driver-pending, not implemented.** ``mssql+pyodbc``
requires the Microsoft ODBC Driver for SQL Server installed at the *system*
level (not a pip package) — genuinely heavy and platform-awkward to add
sight-unseen in this environment, exactly the build prompt's own
"acceptable to mark driver-pending" allowance (§6). ``SUPPORTED_DIALECTS``
below lists only what actually connects today; ``declaration.py``'s
``CONFIG_SCHEMA`` still accepts ``"SQLSERVER"`` as a recognized value so a
config-validation error can name it specifically ("driver-pending") rather
than reporting a bare "invalid enum value."

**Credentials never become a plain string.** ``build_connection_url``
returns a ``sqlalchemy.engine.URL`` — a structured object SQLAlchemy
itself keeps the password component out of ``repr()``/``str()`` for
(``URL.render_as_string()`` requires an explicit ``hide_password=False``
to include it, and this module never calls it that way). ``create_engine``
accepts the ``URL`` object directly; no code path here ever concatenates
host/port/database/username/password into a bare connection string."""

from __future__ import annotations

import threading
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL

_DIALECT_DRIVERNAME = {
    "POSTGRESQL": "postgresql+psycopg2",
    "MYSQL": "mysql+pymysql",
}
SUPPORTED_DIALECTS = frozenset(_DIALECT_DRIVERNAME)
PENDING_DIALECTS = frozenset({"SQLSERVER"})


def build_connection_url(
    dialect: str, host: str, port: int, database: str, *,
    username: str | None = None, password: str | None = None,
) -> URL:
    drivername = _DIALECT_DRIVERNAME[dialect]
    return URL.create(
        drivername=drivername, username=username, password=password,
        host=host, port=port, database=database,
    )


# --------------------------------------------------------------------------- #
# Per-instance engine cache (ACT-INT-FR-126) — an SQLAlchemy ``Engine`` owns a
# real connection pool and is meant to be created once per target and reused,
# not rebuilt on every call (rebuilding on every invocation would silently
# defeat "configurable pool limits" — a fresh, single-connection engine every
# time is not a pool). Keyed by the caller-supplied ``cache_key`` (the
# connector instance id in production; tests use their own keys to avoid
# cross-test pool reuse). A configuration change does not itself evict a
# cached engine in this sub-phase — a known, documented limitation (see
# docs/integration/connectors.md) — acceptable since instance reconfiguration
# is rare relative to invocation volume.
# --------------------------------------------------------------------------- #
_ENGINE_CACHE: dict[Any, Engine] = {}
_ENGINE_CACHE_LOCK = threading.Lock()


def get_or_create_engine(
    cache_key: Any, dialect: str, host: str, port: int, database: str, *,
    username: str | None, password: str | None, pool_size: int, max_overflow: int,
) -> Engine:
    with _ENGINE_CACHE_LOCK:
        engine = _ENGINE_CACHE.get(cache_key)
        if engine is not None:
            return engine
        url = build_connection_url(dialect, host, port, database, username=username, password=password)
        engine = create_engine(url, pool_size=pool_size, max_overflow=max_overflow, pool_pre_ping=True)
        _ENGINE_CACHE[cache_key] = engine
        return engine


def dispose_engine(cache_key: Any) -> None:
    """Disposes and evicts a cached engine (closing its pooled
    connections) — used by tests to avoid leaking connections across
    runs; a real deployment would call this if/when instance
    reconfiguration support evicts the cache (see the module docstring)."""
    with _ENGINE_CACHE_LOCK:
        engine = _ENGINE_CACHE.pop(cache_key, None)
    if engine is not None:
        engine.dispose()
