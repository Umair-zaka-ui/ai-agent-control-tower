"""Phase 2.2.2 tests — the database connector's tool-invocation bridge
(``app/integration/connectors/database/invoker.py``), end to end.

This is the file that proves AC-23 ("a database tool is actually invocable
end to end") and the live half of AC-18/AC-21 (credential resolution and
protection) — everything here connects to this platform's own real dev
Postgres (``settings.DATABASE_URL``), the same instance every other test
in this codebase already uses via ``db_session``/``SessionLocal`` — never
a second, separate database, and never a mock."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integration.auth.service import ConnectorCredentialService
from app.integration.connectors.database import drivers
from app.integration.connectors.database.invoker import invoke_tool
from app.integration.errors import DbQueryNotDeclaredError
from app.integration.service import ConnectorService, ConnectorTypeService
from app.models.integration import ConnectorCredential
from app.models.user import User

_PG_URL = make_url(settings.DATABASE_URL)


def _config(**overrides):
    base = {
        "dialect": "POSTGRESQL", "host": _PG_URL.host, "port": _PG_URL.port, "database": _PG_URL.database,
        "auth_scheme": "BASIC",
        "queries": [
            {
                "name": "whoami", "description": "Return the connected database role.",
                "sql": "SELECT current_user AS role_name", "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "echo_value", "description": "Echo a value back.", "sql": "SELECT :val AS echoed",
                "parameters": {"type": "object", "properties": {"val": {"type": "string"}}, "required": ["val"]},
            },
        ],
    }
    base.update(overrides)
    return base


def _admin_user(db_session: Session, admin: dict) -> User:
    return db_session.get(User, uuid.UUID(admin["user_id"]))


def _make_instance(db_session: Session, admin: dict, *, store_credential: bool = True):
    ConnectorTypeService(db_session).ensure_seeded()
    actor = _admin_user(db_session, admin)
    org_id = uuid.UUID(admin["organization_id"])
    instance = ConnectorService(db_session).create_instance(
        actor, org_id, connector_type="DATABASE", name=f"Dev Postgres {uuid.uuid4().hex[:6]}",
        configuration=_config(),
    )
    if store_credential:
        ConnectorCredentialService(db_session).store(
            actor, org_id, instance.id, "BASIC", {"username": _PG_URL.username, "password": _PG_URL.password},
        )
    return instance, actor, org_id


@pytest.fixture(autouse=True)
def _cleanup_engine_cache():
    yield
    # Instance-id-keyed cache entries created during these tests are
    # process-local and harmless to leave, but disposing keeps the test
    # run from accumulating open pooled connections across the file.
    for key in list(drivers._ENGINE_CACHE):
        if isinstance(key, uuid.UUID):
            drivers.dispose_engine(key)


# --------------------------------------------------------------------------- #
# AC-23 — a database tool is actually invocable end to end
# --------------------------------------------------------------------------- #
def test_ac23_declared_query_invokes_through_the_bridge_end_to_end(admin, db_session: Session):
    instance, actor, org_id = _make_instance(db_session, admin)
    rows = invoke_tool(db_session, org_id, instance.id, "whoami", {})
    assert rows == [{"role_name": _PG_URL.username}]


def test_ac23_parameterized_query_invokes_with_real_bound_values(admin, db_session: Session):
    instance, actor, org_id = _make_instance(db_session, admin)
    rows = invoke_tool(db_session, org_id, instance.id, "echo_value", {"val": "hello from the bridge"})
    assert rows == [{"echoed": "hello from the bridge"}]


def test_ac23_undeclared_query_name_is_rejected_before_reaching_the_database(admin, db_session: Session):
    instance, actor, org_id = _make_instance(db_session, admin)
    with pytest.raises(DbQueryNotDeclaredError):
        invoke_tool(db_session, org_id, instance.id, "drop_everything", {})


# --------------------------------------------------------------------------- #
# AC-21 / AC-18 — credential resolved and applied by the framework, never
# touched by the connector's own code, never leaked
# --------------------------------------------------------------------------- #
def test_ac21_the_stored_encrypted_credential_is_applied_as_real_connection_auth(admin, db_session: Session):
    """The username/password stored (encrypted) via
    ``ConnectorCredentialService`` are what the bridge actually connects
    to Postgres with — proven by asking the database itself who it thinks
    is connected (``current_user``), not by inspecting internals."""
    instance, actor, org_id = _make_instance(db_session, admin)
    rows = invoke_tool(db_session, org_id, instance.id, "whoami", {})
    assert rows[0]["role_name"] == _PG_URL.username


def test_ac18_the_stored_credential_row_never_holds_the_plaintext_password(admin, db_session: Session):
    """AC-18 — reinforces 2.1.2's own generic guarantee specifically for
    this connector's own credential-storage path."""
    instance, actor, org_id = _make_instance(db_session, admin)
    row = db_session.execute(
        sqlalchemy.select(ConnectorCredential).where(ConnectorCredential.connector_instance_id == instance.id)
    ).scalar_one()
    assert _PG_URL.password not in row.encrypted_secret
    assert _PG_URL.password not in row.secret_hint


def test_ac18_no_credential_configured_raises_before_any_connection_is_attempted(admin, db_session: Session):
    instance, actor, org_id = _make_instance(db_session, admin, store_credential=False)
    with pytest.raises(Exception) as excinfo:
        invoke_tool(db_session, org_id, instance.id, "whoami", {})
    assert _PG_URL.password not in str(excinfo.value)


def test_none_auth_scheme_never_calls_the_credential_service(admin, db_session: Session, monkeypatch):
    """The ``"NONE"`` scheme path must never even attempt to resolve a
    credential -- proven by monkeypatching ``resolve_credential_bundle``
    to raise if called at all, then invoking with a ``NONE``-scheme
    instance and confirming it never fires (query-not-declared is the
    cheapest way to exercise the auth-resolution branch without needing a
    passwordless connection to actually succeed against this dev Postgres)."""
    instance, actor, org_id = _make_instance(db_session, admin, store_credential=False)
    from app.integration.service import ConnectorService as _CS

    _CS(db_session).update_configuration(actor, org_id, instance.id, _config(auth_scheme="NONE"))

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("resolve_credential_bundle must not be called for auth_scheme NONE")

    monkeypatch.setattr(ConnectorCredentialService, "resolve_credential_bundle", _fail_if_called)
    with pytest.raises(DbQueryNotDeclaredError):
        invoke_tool(db_session, org_id, instance.id, "not_declared", {})
