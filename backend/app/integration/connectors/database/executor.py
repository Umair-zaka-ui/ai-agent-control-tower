"""Phase 2.2.2 SRS ACT-INT-FR-121, FR-122, FR-123, FR-124 — the
security-critical query executor.

**This module's only public entry point, ``execute_declared_query``, takes
a ``DeclaredQuery`` (fixed, human-authored SQL — see ``declaration.py``)
and a validated parameter mapping. There is no function anywhere in this
module, or reachable through it, that accepts a raw SQL string from a
caller.** That is the actual enforcement of ``ACT-INT-FR-122`` ("reject
any attempt to execute SQL constructed from model output") — not a check
that runs and rejects, but an absence: the operation "run this string as
SQL" is not one this module offers, the same containment-by-omission
principle the SDK used for the raw HTTP client and 2.2.1 used for request
templating.

**Bound, never interpolated (``ACT-INT-FR-123``).** ``query.sql`` is
passed to SQLAlchemy's ``text()`` construct with its own ``:name``
placeholders untouched, and ``params`` is passed alongside as a mapping —
SQLAlchemy hands the SQL string and the parameter mapping to the DBAPI
driver *separately*; the driver (psycopg2/PyMySQL) does the actual binding
at the wire-protocol level. No f-string, ``%``-format, or ``.format()``
call ever builds the executed SQL from a parameter value — there is
nothing in this file that could turn a parameter into SQL structure even
by accident, because the SQL string and the parameter values never touch
each other in Python code at all.

**Row limit (``ACT-INT-FR-124``).** Fetched via ``fetchmany(row_limit +
1)`` — never a bare ``fetchall()`` — so memory use is bounded regardless
of how large the real result would be. A result exceeding the limit is
**rejected outright**, not silently truncated: a truncated result handed
to a model could read as a complete, misleading answer (the same "an
attempt that returned something wrong or partial should say so loudly"
principle Milestone 1's ``TOOL_RESPONSE_TOO_LARGE`` already established
for oversized HTTP responses).

**Timeout (``ACT-INT-FR-124``).** Enforced two ways, not one: (1) for
PostgreSQL/MySQL, a server-side statement-timeout GUC is set for the
duration of the query, so the database itself aborts a runaway query
(defense the client can't be tricked out of); (2) a client-side wall-clock
bound (a single-worker thread + ``Future.result(timeout=...)``) is the
backstop that guarantees this module raises ``QueryTimeoutError`` even if
a dialect's server-side setting doesn't fire for some reason. Because
Python cannot forcibly cancel a blocked DBAPI call, a client-side timeout
does not kill the worker thread outright — it stops waiting on it and
raises immediately; the thread itself exits once the (still-set)
server-side timeout aborts the query, a bounded, self-resolving condition,
never a permanent leak."""

from __future__ import annotations

import concurrent.futures
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.integration.connectors.database.declaration import DeclaredQuery

_STATEMENT_TIMEOUT_SQL = {
    "POSTGRESQL": "SET LOCAL statement_timeout = :timeout_ms",
    "MYSQL": "SET SESSION MAX_EXECUTION_TIME = :timeout_ms",
}
_TIMEOUT_MESSAGE_MARKERS = {
    "POSTGRESQL": ("statement timeout", "canceling statement"),
    "MYSQL": ("execution time exceeded", "max_execution_time"),
}
# Client-side backstop is given a small grace window beyond the declared
# timeout so that, in the common case, the database's own server-side
# timeout (set to the exact same value) fires and is reported first --
# giving an accurate "the database aborted it" classification rather than
# "the client gave up waiting."
_CLIENT_TIMEOUT_GRACE_SECONDS = 1.0


class QueryTimeoutError(Exception):
    """A declared query exceeded its configured timeout — translated to
    ``DbQueryTimeoutError`` at the platform boundary (``invoker.py``)."""


class ResultLimitExceededError(Exception):
    """A declared query's result exceeded its configured row limit —
    translated to ``DbResultLimitExceededError`` at the platform boundary."""


class QueryExecutionError(Exception):
    """A declared query failed for any other driver-level reason. The
    message is always a generic, safe summary (see ``_safe_message``
    below) — never the raw driver exception text, which can embed a
    connection string, host, or credential fragment depending on the
    failure (``ACT-INT-FR-127``)."""


def _looks_like_timeout(dialect: str, exc: Exception) -> bool:
    markers = _TIMEOUT_MESSAGE_MARKERS.get(dialect, ())
    text_lower = str(exc).lower()
    return any(marker in text_lower for marker in markers)


def _safe_message(exc: Exception) -> str:
    """Deliberately generic: a SQLAlchemy/DBAPI exception's own message
    can include the failing statement, parameter values, or (for a
    connection-level failure) the DSN/host — none of that is safe to
    surface to a tool caller or log verbatim. Only the exception's class
    name is included, which is safe (it names a failure category, e.g.
    ``OperationalError``, never any data)."""
    return f"{type(exc).__name__}: database operation failed"


def execute_declared_query(
    engine: Engine, dialect: str, query: DeclaredQuery, params: Mapping[str, Any], *,
    row_limit: int, timeout_seconds: float,
) -> list[dict[str, Any]]:
    """The one, only, public entry point. ``query`` is a ``DeclaredQuery``
    (never a raw string); ``params`` is a plain mapping of already-
    validated parameter values, bound by the driver, never interpolated."""

    def _run() -> list[dict[str, Any]]:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                timeout_statement = _STATEMENT_TIMEOUT_SQL.get(dialect)
                if timeout_statement:
                    connection.execute(text(timeout_statement), {"timeout_ms": max(1, int(timeout_seconds * 1000))})
                result = connection.execute(text(query.sql), dict(params))
                if not result.returns_rows:
                    transaction.commit()
                    return []
                rows = result.fetchmany(row_limit + 1)
                transaction.commit()
            except Exception:
                transaction.rollback()
                raise
            if len(rows) > row_limit:
                raise ResultLimitExceededError(f"query '{query.name}' returned more than {row_limit} rows")
            return [dict(row._mapping) for row in rows]

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run)
        try:
            return future.result(timeout=timeout_seconds + _CLIENT_TIMEOUT_GRACE_SECONDS)
        except concurrent.futures.TimeoutError as exc:
            raise QueryTimeoutError(f"query '{query.name}' exceeded its {timeout_seconds}s timeout") from exc
        except ResultLimitExceededError:
            raise
        except SQLAlchemyError as exc:
            if _looks_like_timeout(dialect, exc):
                raise QueryTimeoutError(f"query '{query.name}' exceeded its {timeout_seconds}s timeout") from exc
            raise QueryExecutionError(_safe_message(exc)) from exc
