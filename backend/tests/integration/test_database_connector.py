"""Phase 2.2.2 tests — Generic Database Connector.

Grouped exactly as the build prompt's §8 groups its acceptance criteria:
the security core (AC-01..06 — the model never writes SQL), declared
queries & parameters (AC-07..10), read-only & limits (AC-11..14), drivers/
pooling/credentials (AC-15..19 — the live-Postgres half of these lives in
``test_database_connector_invocation.py``), SDK-surface & integrity
(AC-20..29).

Every test in this file that touches a real database connects to this
platform's own dev Postgres (``settings.DATABASE_URL``, parsed for its
connection parameters only — never hardcoded, never logged) — the same
"real Postgres, not mocks" discipline this codebase already applies
everywhere else (REPO_STATE §7)."""

from __future__ import annotations

import ast
import inspect
import time
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.integration.connectors.database import declaration, drivers, executor
from app.integration.connectors.database.connector import CONNECTOR_TYPE, CONNECTOR_VERSION, DatabaseConnector
from app.integration.connectors.database.declaration import (
    classify_query,
    mutating_query_names,
    parse_declaration,
    tool_contracts_for,
)
from app.integration.connectors.database.invoker import run_query
from app.integration.errors import (
    DbParameterInvalidError,
    DbQueryNotDeclaredError,
    DbQueryTimeoutError,
    DbResultLimitExceededError,
    DbWriteNotPermittedError,
)
from app.integration.mock import MockConnector
from app.integration.sdk import ConnectorConfigInvalidError, ConnectorTestHarness
from app.integration.service import _CONNECTOR_TYPES, ConnectorTypeService
from app.models.integration import Connector as ConnectorRow

_PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "app" / "integration" / "connectors" / "database"
_SDK_ONLY_FILES = ("declaration.py",)
_DRIVER_FILES = ("drivers.py", "executor.py")
_CONNECTOR_FILE = "connector.py"

_PG_URL = make_url(settings.DATABASE_URL)


def _pg_connection_kwargs() -> dict[str, Any]:
    return {
        "dialect": "POSTGRESQL", "host": _PG_URL.host, "port": _PG_URL.port, "database": _PG_URL.database,
    }


def _config(**overrides: Any) -> dict[str, Any]:
    base = {
        **_pg_connection_kwargs(),
        "auth_scheme": "NONE",
        "queries": [
            {
                "name": "echo_value", "description": "Echo a value back.", "sql": "SELECT :val AS echoed",
                "parameters": {"type": "object", "properties": {"val": {"type": "string"}}, "required": ["val"]},
            },
        ],
    }
    base.update(overrides)
    return base


def _engine():
    return drivers.get_or_create_engine(
        "test_database_connector", "POSTGRESQL", _PG_URL.host, _PG_URL.port, _PG_URL.database,
        username=_PG_URL.username, password=_PG_URL.password, pool_size=3, max_overflow=2,
    )


@pytest.fixture(autouse=True, scope="module")
def _cleanup_engine_cache():
    yield
    drivers.dispose_engine("test_database_connector")


# --------------------------------------------------------------------------- #
# The security core (AC-01..06) — the model never writes SQL
# --------------------------------------------------------------------------- #
def test_ac01_no_api_accepts_raw_sql():
    """AC-01 — verified by absence: ``execute_declared_query``'s only
    parameters are an engine, a dialect, a ``DeclaredQuery``, a parameter
    mapping, a row limit, and a timeout. No parameter anywhere in this
    package's public surface is a raw SQL string."""
    params = list(inspect.signature(executor.execute_declared_query).parameters)
    assert params == ["engine", "dialect", "query", "params", "row_limit", "timeout_seconds"]
    # The `query` parameter is typed as a `DeclaredQuery`, not `str` --
    # confirmed structurally via the annotation, not just the name.
    annotation = inspect.signature(executor.execute_declared_query).parameters["query"].annotation
    assert annotation == "DeclaredQuery"


def test_ac02_bound_injection_payload_is_inert_against_real_postgres():
    """AC-02 — the exact adversarial value from the build prompt."""
    decl = parse_declaration(_config())
    rows = run_query(decl, _engine(), "echo_value", {"val": "'; DROP TABLE users; --"})
    assert rows == [{"echoed": "'; DROP TABLE users; --"}]
    # And the platform's own `users` table is still there.
    with _engine().connect() as conn:
        conn.execute(sqlalchemy.text("SELECT 1 FROM users LIMIT 1"))


@pytest.mark.parametrize("payload", [
    "' OR '1'='1",
    "' UNION SELECT current_user --",
    "x'; SELECT 1; --",
    "admin'--",
    "1' AND 1=1 UNION ALL SELECT NULL,NULL,NULL--",
])
def test_ac03_classic_injection_payloads_as_parameters_are_inert(payload):
    """AC-03."""
    decl = parse_declaration(_config())
    rows = run_query(decl, _engine(), "echo_value", {"val": payload})
    assert rows == [{"echoed": payload}]


def test_ac04_an_undeclared_query_name_is_rejected():
    """AC-04."""
    decl = parse_declaration(_config())
    with pytest.raises(DbQueryNotDeclaredError) as excinfo:
        run_query(decl, None, "not_a_real_query", {})
    assert excinfo.value.code == "DB_QUERY_NOT_DECLARED"


def test_ac05_parameters_are_bound_not_interpolated_verified_by_inspecting_execution():
    """AC-05 — inspects the literal SQL text and parameter mapping
    SQLAlchemy actually hands to the DBAPI driver (via its own
    ``before_cursor_execute`` event), not merely the outcome."""
    decl = parse_declaration(_config())
    engine = _engine()
    captured: list[tuple[str, Any]] = []

    def _listener(conn, cursor, statement, parameters, context, executemany):
        captured.append((statement, parameters))

    sqlalchemy.event.listen(engine, "before_cursor_execute", _listener)
    try:
        run_query(decl, engine, "echo_value", {"val": "'; DROP TABLE users; --"})
    finally:
        sqlalchemy.event.remove(engine, "before_cursor_execute", _listener)

    statements = [s for s, _ in captured]
    # The literal SQL sent to the driver still contains the placeholder
    # token, never the parameter value substituted into the text.
    assert any("DROP TABLE" not in s and "val" in s for s in statements)
    assert all("DROP TABLE" not in s for s in statements)


def test_ac06_no_code_path_from_model_text_to_sql_structure_verified_by_construction():
    """AC-06 — ``invoker.run_query``'s only way to reach a query is by
    name (must match a declaration); its only way to supply data is a
    parameter mapping, JSON-Schema-validated before it ever reaches the
    executor."""
    sig = inspect.signature(run_query)
    assert list(sig.parameters) == ["decl", "engine", "query_name", "params"]
    # No parameter is documented/typed as raw SQL.
    for name in sig.parameters:
        assert name not in ("sql", "raw_sql", "query_text", "statement")


# --------------------------------------------------------------------------- #
# Declared queries & parameters (AC-07..10)
# --------------------------------------------------------------------------- #
def test_ac07_each_declared_query_becomes_a_distinct_tool_contract():
    """AC-07."""
    config = _config(queries=[
        {"name": "get_a", "description": "a", "sql": "SELECT 1 AS a", "parameters": {"type": "object", "properties": {}}},
        {"name": "get_b", "description": "b", "sql": "SELECT 2 AS b", "parameters": {"type": "object", "properties": {}}},
    ])
    contracts = tool_contracts_for(config)
    assert [c.name for c in contracts] == ["get_a", "get_b"]
    assert contracts[0].description == "a"


def test_ac08_supplied_parameters_are_validated_against_the_declared_schema():
    """AC-08."""
    decl = parse_declaration(_config())
    with pytest.raises(DbParameterInvalidError):
        run_query(decl, _engine(), "echo_value", {"val": 123})  # wrong type (schema wants string)


def test_ac09_a_missing_required_parameter_is_rejected():
    """AC-09."""
    decl = parse_declaration(_config())
    with pytest.raises(DbParameterInvalidError) as excinfo:
        run_query(decl, _engine(), "echo_value", {})
    assert excinfo.value.code == "DB_PARAMETER_INVALID"


def test_ac10_results_map_to_the_declared_shape():
    """AC-10."""
    decl = parse_declaration(_config())
    rows = run_query(decl, _engine(), "echo_value", {"val": "hello"})
    assert rows == [{"echoed": "hello"}]


# --------------------------------------------------------------------------- #
# Read-only & limits (AC-11..14)
# --------------------------------------------------------------------------- #
def test_ac11_a_read_only_instance_rejects_a_mutating_query_at_config_time():
    """AC-11."""
    config = _config(read_only=True, queries=[
        {"name": "delete_all", "description": "x", "sql": "DELETE FROM some_table",
         "parameters": {"type": "object", "properties": {}}},
    ])
    with pytest.raises(DbWriteNotPermittedError) as excinfo:
        DatabaseConnector().validate_configuration(config)
    assert excinfo.value.code == "DB_WRITE_NOT_PERMITTED"


def test_ac11_classify_query_is_fail_closed_and_comment_aware():
    assert classify_query("SELECT * FROM x") == "READ"
    assert classify_query("  \n  WITH cte AS (SELECT 1) SELECT * FROM cte") == "READ"
    assert classify_query("DELETE FROM x") == "WRITE"
    assert classify_query("-- SELECT\nDROP TABLE x") == "WRITE"
    assert classify_query("/* SELECT */ UPDATE x SET y = 1") == "WRITE"
    assert classify_query("EXEC some_proc") == "WRITE"


def test_ac12_read_only_is_the_default_write_requires_explicit_configuration():
    """AC-12."""
    decl_default = parse_declaration(_config())
    assert decl_default.read_only is True
    decl_explicit = parse_declaration(_config(read_only=False))
    assert decl_explicit.read_only is False
    # A read-only instance with only read queries validates cleanly.
    DatabaseConnector().validate_configuration(_config())


def test_ac13_a_result_exceeding_the_row_limit_is_rejected_not_truncated():
    """AC-13 — stated policy: reject, never silently truncate."""
    config = _config(default_row_limit=3, queries=[
        {"name": "gen", "description": "x", "sql": "SELECT generate_series(1, 10) AS n",
         "parameters": {"type": "object", "properties": {}}},
    ])
    decl = parse_declaration(config)
    with pytest.raises(DbResultLimitExceededError) as excinfo:
        run_query(decl, _engine(), "gen", {})
    assert excinfo.value.code == "DB_RESULT_LIMIT_EXCEEDED"


def test_ac13_a_result_within_the_row_limit_succeeds():
    config = _config(default_row_limit=20, queries=[
        {"name": "gen", "description": "x", "sql": "SELECT generate_series(1, 5) AS n",
         "parameters": {"type": "object", "properties": {}}},
    ])
    decl = parse_declaration(config)
    rows = run_query(decl, _engine(), "gen", {})
    assert len(rows) == 5


def test_ac14_a_query_exceeding_the_timeout_is_terminated():
    """AC-14."""
    config = _config(queries=[
        {"name": "slow", "description": "x", "sql": "SELECT pg_sleep(3)",
         "parameters": {"type": "object", "properties": {}}, "timeout_seconds": 1},
    ])
    decl = parse_declaration(config)
    start = time.monotonic()
    with pytest.raises(DbQueryTimeoutError) as excinfo:
        run_query(decl, _engine(), "slow", {})
    elapsed = time.monotonic() - start
    assert excinfo.value.code == "DB_QUERY_TIMEOUT"
    assert elapsed < 3  # the timeout fired, not the full sleep


# --------------------------------------------------------------------------- #
# Drivers, pooling, credentials (AC-15..19; the live-credential half is in
# test_database_connector_invocation.py)
# --------------------------------------------------------------------------- #
def test_ac15_the_postgresql_driver_executes_a_declared_query_end_to_end():
    """AC-15."""
    decl = parse_declaration(_config())
    rows = run_query(decl, _engine(), "echo_value", {"val": "real-postgres"})
    assert rows == [{"echoed": "real-postgres"}]


def test_ac16_vendor_placeholder_styles_are_handled_inside_drivers():
    """AC-16 — the declaration model uses one uniform ``:name`` syntax
    regardless of dialect; `drivers.py` maps each dialect to its own
    SQLAlchemy drivername, which is what performs the actual placeholder
    translation (verified structurally: both dialects are declarable with
    the identical `:val` syntax in `_config`'s own query)."""
    assert drivers.SUPPORTED_DIALECTS == frozenset({"POSTGRESQL", "MYSQL"})
    assert drivers._DIALECT_DRIVERNAME["POSTGRESQL"] == "postgresql+psycopg2"
    assert drivers._DIALECT_DRIVERNAME["MYSQL"] == "mysql+pymysql"
    mysql_decl = parse_declaration(_config(dialect="MYSQL", port=3306))
    assert mysql_decl.queries[0].sql == "SELECT :val AS echoed"  # identical declaration syntax


def test_ac16_sqlserver_is_recognized_but_driver_pending():
    with pytest.raises(ConnectorConfigInvalidError) as excinfo:
        parse_declaration(_config(dialect="SQLSERVER", port=1433))
    assert "driver-pending" in str(excinfo.value)
    assert "SQLSERVER" in drivers.PENDING_DIALECTS
    assert "SQLSERVER" not in drivers.SUPPORTED_DIALECTS


def test_ac17_connection_pooling_is_per_instance_with_a_configurable_limit():
    """AC-17."""
    engine = drivers.get_or_create_engine(
        "test_pool_config", "POSTGRESQL", _PG_URL.host, _PG_URL.port, _PG_URL.database,
        username=_PG_URL.username, password=_PG_URL.password, pool_size=7, max_overflow=4,
    )
    try:
        assert engine.pool.size() == 7
        assert engine.pool._max_overflow == 4
        # Same cache key returns the identical engine/pool -- reused, not rebuilt.
        again = drivers.get_or_create_engine(
            "test_pool_config", "POSTGRESQL", _PG_URL.host, _PG_URL.port, _PG_URL.database,
            username=_PG_URL.username, password=_PG_URL.password, pool_size=99, max_overflow=99,
        )
        assert again is engine
        assert engine.pool.size() == 7  # the second call's params did not rebuild the pool
    finally:
        drivers.dispose_engine("test_pool_config")


def test_ac18_the_connection_string_never_appears_in_a_row_limit_or_timeout_error():
    """AC-18 (structural half — the credential-in-audit/log half is
    covered live in test_database_connector_invocation.py)."""
    decl = parse_declaration(_config(default_row_limit=1, queries=[
        {"name": "gen", "description": "x", "sql": "SELECT generate_series(1, 3) AS n",
         "parameters": {"type": "object", "properties": {}}},
    ]))
    with pytest.raises(DbResultLimitExceededError) as excinfo:
        run_query(decl, _engine(), "gen", {})
    assert _PG_URL.password not in excinfo.value.message
    assert str(_PG_URL.host) not in excinfo.value.message


def test_ac19_a_connection_failure_error_does_not_echo_the_connection_string():
    """AC-19 — connects to a port nothing is listening on."""
    from app.integration.connectors.database.invoker import invoke_tool  # noqa: F401  (import sanity only)
    from app.integration.errors import DbConnectionFailedError

    bad_engine = drivers.get_or_create_engine(
        "test_bad_connection", "POSTGRESQL", "127.0.0.1", 1, "nope",
        username="nobody", password="totally-secret-password-value", pool_size=1, max_overflow=0,
    )
    try:
        decl = parse_declaration(_config())
        with pytest.raises(DbConnectionFailedError) as excinfo:
            run_query(decl, bad_engine, "echo_value", {"val": "x"})
        assert "totally-secret-password-value" not in excinfo.value.message
        assert "nope" not in excinfo.value.message
    finally:
        drivers.dispose_engine("test_bad_connection")


# --------------------------------------------------------------------------- #
# SDK-surface & integrity (AC-20..29)
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


def test_ac20_declaration_py_imports_only_from_the_sdk_surface():
    """AC-20 — the pure-declaration module stays exactly as SDK-surface-
    restricted as 2.2.1's own equivalent."""
    for filename in _SDK_ONLY_FILES:
        for module in _app_imports(_PACKAGE_ROOT / filename):
            assert module == "app.integration.sdk" or module.startswith("app.integration.sdk."), (
                f"{filename} imports {module!r}, reaching past the SDK surface"
            )


def test_ac20_connector_py_has_exactly_one_justified_surface_deviation():
    """AC-20 — the one, specific, documented deviation: `connector.py`
    additionally imports `DbWriteNotPermittedError` from
    `app.integration.errors`, needed for the config-time write-permission
    check (`ACT-INT-FR-125`) that 2.2.1 never needed. Nothing else."""
    modules = _app_imports(_PACKAGE_ROOT / _CONNECTOR_FILE)
    non_sdk = {m for m in modules if not (m == "app.integration.sdk" or m.startswith("app.integration.sdk."))
               and not m.startswith("app.integration.connectors.database")}
    assert non_sdk == {"app.integration.errors"}


def test_ac21_the_connector_never_receives_raw_credential_material():
    """AC-21 — `DatabaseConnector`'s ABC methods take no db/session/
    credential parameter; its own file never imports the auth framework
    or a database driver at all."""
    for method_name in ("describe", "validate_configuration", "health_check"):
        params = list(inspect.signature(getattr(DatabaseConnector, method_name)).parameters)
        assert all(p in ("self", "configuration") for p in params)
    modules = _app_imports(_PACKAGE_ROOT / _CONNECTOR_FILE)
    assert not any(m.startswith("app.integration.auth") for m in modules)
    assert not any("sqlalchemy" in m.lower() for m in modules)


def test_ac22_registration_parity_with_mock_webhook_rest(db_session):
    """AC-22."""
    assert _CONNECTOR_TYPES["DATABASE"] is DatabaseConnector
    service = ConnectorTypeService(db_session)
    service.ensure_seeded()
    from sqlalchemy import select
    row = db_session.execute(
        select(ConnectorRow).where(ConnectorRow.connector_type == CONNECTOR_TYPE, ConnectorRow.version == CONNECTOR_VERSION)
    ).scalar_one()
    assert row.connector_type == "DATABASE"


def test_ac24_2_1_x_and_2_2_1_connectors_still_describe_and_validate_unchanged():
    """AC-24."""
    assert MockConnector().describe().auth_requirements == {"scheme": "NONE"}
    from app.integration.connectors.rest.connector import RestConnector
    assert RestConnector().describe().connector_type == "REST"


def test_ac26_migration_head_unchanged_no_new_migration_needed():
    """AC-26 — every table this connector touches already exists."""
    migrations_dir = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    versions = sorted(p.name for p in migrations_dir.glob("00*.py"))
    # Updated Phase 3.5: a genuinely new migration landed for the canary
    # rollout engine (0041).
    assert versions[-1] == "0043_distributed_scheduler.py"


def test_ac29_no_stub_markers_in_this_phases_new_files():
    """AC-29."""
    forbidden = ("TODO", "FIXME", "XXX", "HACK", "NotImplementedError", "pytest.skip", "xfail")
    for filename in list(_SDK_ONLY_FILES) + list(_DRIVER_FILES) + [_CONNECTOR_FILE, "invoker.py", "__init__.py"]:
        text_content = (_PACKAGE_ROOT / filename).read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text_content, f"{filename} contains forbidden marker {marker!r}"


def test_mutating_query_names_is_pure_data_never_raises():
    config = _config(queries=[
        {"name": "read_one", "description": "x", "sql": "SELECT 1", "parameters": {"type": "object", "properties": {}}},
        {"name": "write_one", "description": "x", "sql": "UPDATE x SET y=1",
         "parameters": {"type": "object", "properties": {}}},
    ])
    decl = parse_declaration(config)
    assert mutating_query_names(decl) == ["write_one"]


def test_database_config_harness_roundtrip():
    """Standard 2.1.4-harness usage, mirroring the REST connector's own
    AC-03-equivalent proof that the SDK testing utilities work here too."""
    harness = ConnectorTestHarness(DatabaseConnector())
    harness.assert_configuration_valid(_config())
    message = harness.assert_configuration_invalid({"dialect": "POSTGRESQL"})  # missing required keys
    assert message
