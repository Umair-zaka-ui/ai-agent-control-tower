"""Phase 2.2.3 tests — Generic File & Object Storage Connector.

Grouped as the build prompt's §8 groups its acceptance criteria: scope,
operations & limits (AC-12..16), backends & credential protection
(AC-17..20, structural half — the live-database half of AC-19/AC-20/
AC-23/AC-24 is in ``test_storage_connector_invocation.py``), SDK-surface
& integrity (AC-21..30).

Filesystem-backend tests use real ``tmp_path`` directories and real file
I/O — never a mock filesystem. The S3-backend dispatch tests mock
``boto3.client`` (no live AWS/MinIO reachable in this environment) to
prove correct ``Bucket``/``Key`` dispatch and error translation; the
*containment* logic itself (which key ends up being requested at all) is
proven with no mocking whatsoever in ``test_storage_scope.py``. This is
the coverage boundary this phase's own build prompt asks to have stated
explicitly (§6/§9.2): S3-compatible dispatch is proven against a mocked
client, not a live object store — see ``docs/integration/connectors.md``."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any

import pytest

from app.integration.connectors.storage import backends, declaration
from app.integration.connectors.storage.connector import CONNECTOR_TYPE, CONNECTOR_VERSION, StorageConnector
from app.integration.connectors.storage.declaration import parse_declaration, tool_contracts_for, write_scope_names
from app.integration.connectors.storage.invoker import run_access
from app.integration.errors import (
    StorageObjectNotFoundError,
    StorageObjectTooLargeError,
    StoragePathDeniedError,
    StorageScopeInvalidError,
    StorageWriteNotPermittedError,
)
from app.integration.mock import MockConnector
from app.integration.sdk import ConnectorTestHarness
from app.integration.service import _CONNECTOR_TYPES, ConnectorTypeService

_PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "app" / "integration" / "connectors" / "storage"
_ALL_PACKAGE_FILES = ("__init__.py", "scope.py", "declaration.py", "backends.py", "connector.py", "invoker.py")


def _fs_config(tmp_path, **overrides: Any) -> dict[str, Any]:
    base = {
        "backend": "FILESYSTEM",
        "scopes": [
            {
                "name": "read_reports", "description": "Read report files.", "operation": "READ",
                "base_directory": str(tmp_path),
            },
        ],
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# Scope, operations, limits (AC-12..16)
# --------------------------------------------------------------------------- #
def test_ac12_a_read_within_declared_scope_succeeds(tmp_path):
    """AC-12."""
    (tmp_path / "q1.txt").write_text("quarter one", encoding="utf-8")
    decl = parse_declaration(_fs_config(tmp_path))
    data = run_access(decl, decl.scopes[0], "q1.txt", {})
    assert data == b"quarter one"


def test_ac13_each_declared_scope_becomes_a_distinct_tool_contract(tmp_path):
    """AC-13."""
    config = _fs_config(tmp_path, scopes=[
        {"name": "read_a", "description": "a", "operation": "READ", "base_directory": str(tmp_path)},
        {"name": "read_b", "description": "b", "operation": "READ", "base_directory": str(tmp_path)},
    ])
    contracts = tool_contracts_for(config)
    assert [c.name for c in contracts] == ["read_a", "read_b"]
    assert contracts[0].parameters == {
        "type": "object", "properties": {"path": {"type": "string", "minLength": 1}},
        "required": ["path"], "additionalProperties": False,
    }


def test_ac14_read_only_is_default_write_scope_rejected_at_config_time(tmp_path):
    """AC-14."""
    config = _fs_config(tmp_path, scopes=[
        {"name": "write_reports", "description": "x", "operation": "WRITE", "base_directory": str(tmp_path)},
    ])
    with pytest.raises(StorageWriteNotPermittedError) as excinfo:
        StorageConnector().validate_configuration(config)
    assert excinfo.value.code == "STORAGE_WRITE_NOT_PERMITTED"

    # explicit read_only=False permits the identical scope.
    StorageConnector().validate_configuration({**config, "read_only": False})


def test_ac14_write_scope_names_is_pure_data_never_raises(tmp_path):
    config = _fs_config(tmp_path, scopes=[
        {"name": "read_one", "description": "x", "operation": "READ", "base_directory": str(tmp_path)},
        {"name": "write_one", "description": "x", "operation": "WRITE", "base_directory": str(tmp_path)},
    ])
    decl = parse_declaration(config)
    assert write_scope_names(decl) == ["write_one"]


def test_ac15_a_read_of_an_oversized_object_is_rejected_without_loading_it(tmp_path, monkeypatch):
    """AC-15 — the size check (``os.path.getsize``) rejects before
    ``open`` is ever called; proven by making ``open`` itself fail the
    test if reached."""
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * 1000)
    config = _fs_config(tmp_path, default_max_object_size_bytes=10, scopes=[
        {"name": "read_reports", "description": "x", "operation": "READ", "base_directory": str(tmp_path)},
    ])
    decl = parse_declaration(config)

    def _fail_if_opened(*args, **kwargs):
        raise AssertionError("open() must not be called once the size check has already rejected the object")

    monkeypatch.setattr("builtins.open", _fail_if_opened)
    with pytest.raises(StorageObjectTooLargeError) as excinfo:
        run_access(decl, decl.scopes[0], "big.bin", {})
    assert excinfo.value.code == "STORAGE_OBJECT_TOO_LARGE"


def test_ac16_a_write_exceeding_the_size_limit_is_rejected(tmp_path):
    """AC-16."""
    config = _fs_config(tmp_path, read_only=False, default_max_object_size_bytes=5, scopes=[
        {"name": "write_reports", "description": "x", "operation": "WRITE", "base_directory": str(tmp_path)},
    ])
    decl = parse_declaration(config)
    with pytest.raises(StorageObjectTooLargeError):
        run_access(decl, decl.scopes[0], "out.txt", {}, content=b"way too many bytes")
    assert not (tmp_path / "out.txt").exists()


# --------------------------------------------------------------------------- #
# Backends & credential protection (AC-17..20, structural half)
# --------------------------------------------------------------------------- #
def test_ac17_the_filesystem_backend_reads_within_scope_end_to_end(tmp_path):
    """AC-17."""
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "file.txt").write_text("nested content", encoding="utf-8")
    decl = parse_declaration(_fs_config(tmp_path))
    data = run_access(decl, decl.scopes[0], "sub/file.txt", {})
    assert data == b"nested content"


def test_ac17_the_filesystem_backend_writes_within_scope_end_to_end(tmp_path):
    config = _fs_config(tmp_path, read_only=False, scopes=[
        {"name": "write_reports", "description": "x", "operation": "WRITE", "base_directory": str(tmp_path)},
    ])
    decl = parse_declaration(config)
    written = run_access(decl, decl.scopes[0], "new/nested/out.txt", {}, content=b"hello world")
    assert written == 11
    assert (tmp_path / "new" / "nested" / "out.txt").read_bytes() == b"hello world"


def test_ac17_a_read_of_a_missing_object_is_not_found(tmp_path):
    decl = parse_declaration(_fs_config(tmp_path))
    with pytest.raises(StorageObjectNotFoundError) as excinfo:
        run_access(decl, decl.scopes[0], "does-not-exist.txt", {})
    assert excinfo.value.code == "STORAGE_OBJECT_NOT_FOUND"


def test_ac17_a_traversal_attempt_through_the_bridge_is_denied_before_any_backend_call(tmp_path):
    decl = parse_declaration(_fs_config(tmp_path))
    with pytest.raises(StoragePathDeniedError) as excinfo:
        run_access(decl, decl.scopes[0], "../../etc/passwd", {})
    assert excinfo.value.code == "STORAGE_PATH_DENIED"


def test_ac18_s3_backend_dispatches_head_and_get_with_the_validated_bucket_and_key(monkeypatch):
    """AC-18 (mocked-client half — no live AWS/MinIO reachable in this
    environment, see this file's own module docstring for the stated
    coverage boundary). Proves ``backends.read_object`` calls
    ``head_object``/``get_object`` with exactly the bucket and the
    already scope-validated key -- never a raw, unvalidated value."""
    calls: list[tuple[str, dict]] = []

    class _FakeBody:
        def read(self, n):
            return b"object-bytes"

    class _FakeClient:
        def head_object(self, **kwargs):
            calls.append(("head_object", kwargs))
            return {"ContentLength": 12}

        def get_object(self, **kwargs):
            calls.append(("get_object", kwargs))
            return {"Body": _FakeBody()}

    monkeypatch.setattr("boto3.client", lambda *a, **k: _FakeClient())
    config = {
        "backend": "S3",
        "scopes": [{"name": "read_docs", "description": "x", "operation": "READ", "bucket": "acme-data", "prefix": "reports"}],
    }
    decl = parse_declaration(config)
    data = run_access(decl, decl.scopes[0], "q1/summary.txt", {})
    assert data == b"object-bytes"
    assert calls[0] == ("head_object", {"Bucket": "acme-data", "Key": "reports/q1/summary.txt"})
    assert calls[1] == ("get_object", {"Bucket": "acme-data", "Key": "reports/q1/summary.txt"})


def test_ac18_s3_not_found_translates_to_storage_object_not_found(monkeypatch):
    from botocore.exceptions import ClientError

    class _FakeClient:
        def head_object(self, **kwargs):
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")

    monkeypatch.setattr("boto3.client", lambda *a, **k: _FakeClient())
    config = {
        "backend": "S3",
        "scopes": [{"name": "read_docs", "description": "x", "operation": "READ", "bucket": "acme-data"}],
    }
    decl = parse_declaration(config)
    with pytest.raises(StorageObjectNotFoundError):
        run_access(decl, decl.scopes[0], "missing.txt", {})


def test_ac18_azure_blob_is_recognized_but_backend_pending():
    with pytest.raises(StorageScopeInvalidError) as excinfo:
        parse_declaration({
            "backend": "AZURE_BLOB",
            "scopes": [{"name": "read_docs", "description": "x", "operation": "READ", "bucket": "acme-data"}],
        })
    assert "backend-pending" in str(excinfo.value)
    assert "AZURE_BLOB" in backends.PENDING_BACKENDS
    assert "AZURE_BLOB" not in backends.SUPPORTED_BACKENDS


def test_ac19_the_platform_error_message_is_generic_never_a_raw_path_or_credential(tmp_path):
    """AC-19/AC-20 (structural half) — ``backends._safe_message`` only
    ever includes the failing exception's class name."""
    exc = OSError("failed for host secret-internal-host with password hunter2")
    assert backends._safe_message(exc) == "OSError: storage operation failed"


def test_ac20_credential_is_never_embedded_in_a_platform_error_message(tmp_path):
    config = _fs_config(tmp_path, read_only=False, scopes=[
        {"name": "write_reports", "description": "x", "operation": "WRITE", "base_directory": str(tmp_path)},
    ])
    decl = parse_declaration(config)
    with pytest.raises(StorageObjectTooLargeError) as excinfo:
        run_access(
            decl, decl.scopes[0], "out.txt", {"username": "s3-access-key", "password": "s3-secret-value"},
            content=b"x" * (decl.default_max_object_size_bytes + 1),
        )
    assert "s3-secret-value" not in excinfo.value.message
    assert "s3-access-key" not in excinfo.value.message


# --------------------------------------------------------------------------- #
# SDK-surface & integrity (AC-21..30)
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


def test_ac21_scope_py_has_zero_app_dependencies():
    """AC-21/AC-11 — the security-critical enforcer imports nothing from
    this platform at all, not even the SDK."""
    assert _app_imports(_PACKAGE_ROOT / "scope.py") == set()


def test_ac21_declaration_py_has_exactly_one_justified_deviation():
    """AC-21 — declaration.py imports the SDK surface plus exactly one
    additional, documented type (``StorageScopeInvalidError``) — see the
    module's own docstring for why this phase needed one where 2.2.2's
    declaration.py needed none."""
    modules = _app_imports(_PACKAGE_ROOT / "declaration.py")
    non_sdk = {m for m in modules if not (m == "app.integration.sdk" or m.startswith("app.integration.sdk."))
               and not m.startswith("app.integration.connectors.storage")}
    assert non_sdk == {"app.integration.errors"}


def test_ac21_connector_py_has_exactly_two_justified_deviations():
    """AC-21 — connector.py imports the SDK surface plus exactly the two
    documented exception types (``StorageScopeInvalidError`` — re-raised
    from ``parse_declaration``'s own semantic errors — and
    ``StorageWriteNotPermittedError`` — this file's own, for the
    read-only/write-scope config-time check)."""
    modules = _app_imports(_PACKAGE_ROOT / "connector.py")
    non_sdk = {m for m in modules if not (m == "app.integration.sdk" or m.startswith("app.integration.sdk."))
               and not m.startswith("app.integration.connectors.storage")}
    assert non_sdk == {"app.integration.errors"}


def test_ac21_backends_py_never_imports_platform_error_types():
    """AC-21 — mirrors 2.2.2's ``executor.py`` discipline: local
    exceptions only, translated to platform errors exclusively by
    ``invoker.py``."""
    modules = _app_imports(_PACKAGE_ROOT / "backends.py")
    assert not any(m.startswith("app.integration.errors") for m in modules)


def test_ac22_the_connector_never_receives_raw_credential_material():
    """AC-22 — ``StorageConnector``'s ABC methods take no db/session/
    credential parameter; its own file never imports the auth framework
    or a storage SDK at all."""
    for method_name in ("describe", "validate_configuration", "health_check"):
        params = list(inspect.signature(getattr(StorageConnector, method_name)).parameters)
        assert all(p in ("self", "configuration") for p in params)
    modules = _app_imports(_PACKAGE_ROOT / "connector.py")
    assert not any(m.startswith("app.integration.auth") for m in modules)
    source = (_PACKAGE_ROOT / "connector.py").read_text(encoding="utf-8")
    assert "import boto3" not in source


def test_ac23_registration_parity_with_mock_rest_database(db_session):
    """AC-23."""
    assert _CONNECTOR_TYPES["STORAGE"] is StorageConnector
    service = ConnectorTypeService(db_session)
    service.ensure_seeded()
    from sqlalchemy import select

    from app.models.integration import Connector as ConnectorRow
    row = db_session.execute(
        select(ConnectorRow).where(ConnectorRow.connector_type == CONNECTOR_TYPE, ConnectorRow.version == CONNECTOR_VERSION)
    ).scalar_one()
    assert row.connector_type == "STORAGE"


def test_ac25_2_1_x_and_2_2_x_connectors_still_describe_and_validate_unchanged():
    """AC-25."""
    assert MockConnector().describe().auth_requirements == {"scheme": "NONE"}
    from app.integration.connectors.database.connector import DatabaseConnector
    from app.integration.connectors.rest.connector import RestConnector
    assert RestConnector().describe().connector_type == "REST"
    assert DatabaseConnector().describe().connector_type == "DATABASE"


def test_ac27_migration_head_unchanged_no_new_migration_needed():
    """AC-27 — every table this connector touches already exists
    (``connectors``/``connector_instances``/``connector_credentials``/
    ``authorization_audit``)."""
    migrations_dir = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    versions = sorted(p.name for p in migrations_dir.glob("00*.py"))
    # Updated Phase 3.5: a genuinely new migration landed for the canary
    # rollout engine (0041).
    assert versions[-1] == "0041_canary_rollout.py"


def test_ac30_no_stub_markers_in_this_phases_new_files():
    """AC-30."""
    forbidden = ("TODO", "FIXME", "XXX", "HACK", "NotImplementedError", "pytest.skip", "xfail")
    for filename in _ALL_PACKAGE_FILES:
        text_content = (_PACKAGE_ROOT / filename).read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text_content, f"{filename} contains forbidden marker {marker!r}"


def test_storage_config_harness_roundtrip(tmp_path):
    """Standard 2.1.4-harness usage, mirroring 2.2.1/2.2.2's own proof
    that the SDK testing utilities work here too."""
    harness = ConnectorTestHarness(StorageConnector())
    harness.assert_configuration_valid(_fs_config(tmp_path))
    message = harness.assert_configuration_invalid({"backend": "FILESYSTEM"})  # missing required 'scopes'
    assert message


def test_a_filesystem_scope_missing_base_directory_is_rejected():
    with pytest.raises(StorageScopeInvalidError):
        parse_declaration({
            "backend": "FILESYSTEM",
            "scopes": [{"name": "read_x", "description": "x", "operation": "READ"}],
        })


def test_an_s3_scope_missing_bucket_is_rejected():
    with pytest.raises(StorageScopeInvalidError):
        parse_declaration({
            "backend": "S3",
            "scopes": [{"name": "read_x", "description": "x", "operation": "READ"}],
        })


def test_duplicate_scope_names_are_rejected(tmp_path):
    with pytest.raises(StorageScopeInvalidError):
        parse_declaration(_fs_config(tmp_path, scopes=[
            {"name": "dup", "description": "a", "operation": "READ", "base_directory": str(tmp_path)},
            {"name": "dup", "description": "b", "operation": "READ", "base_directory": str(tmp_path)},
        ]))


def test_health_check_filesystem_reports_reachability(tmp_path):
    ok_config = _fs_config(tmp_path)
    assert StorageConnector().health_check(ok_config) is True

    missing_dir = str(tmp_path / "does-not-exist")
    bad_config = _fs_config(tmp_path, scopes=[
        {"name": "read_x", "description": "x", "operation": "READ", "base_directory": missing_dir},
    ])
    assert StorageConnector().health_check(bad_config) is False


def test_health_check_object_store_uses_injected_connector_factory():
    calls = []

    class _FakeConn:
        def close(self):
            pass

    def _factory(address, timeout):
        calls.append(address)
        return _FakeConn()

    config = {
        "backend": "S3",
        "scopes": [{"name": "read_docs", "description": "x", "operation": "READ", "bucket": "acme-data"}],
    }
    connector = StorageConnector(connector_factory=_factory)
    assert connector.health_check(config) is True
    assert calls == [("s3.amazonaws.com", 443)]
