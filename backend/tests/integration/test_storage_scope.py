"""Phase 2.2.3 tests — the isolated scope enforcer
(``app/integration/connectors/storage/scope.py``), the security core.

Every test in this file runs with **no live storage of any kind** — no
filesystem I/O beyond ``tempfile``-created fixtures used purely as real
boundaries to canonicalize against (AC-11), no S3/network call anywhere.
This is the storage analogue of ``test_database_connector.py``'s AC-01..06
group: the traversal/scope-escape defense proven in complete isolation
from any backend."""

from __future__ import annotations

import os
import subprocess
import tempfile

import pytest

from app.integration.connectors.storage.scope import (
    FILESYSTEM,
    OBJECT_STORE,
    ScopeBoundary,
    ScopeViolationError,
    resolve_and_contain,
)


@pytest.fixture
def fs_boundary(tmp_path):
    base = tmp_path / "scope_root"
    base.mkdir()
    return ScopeBoundary(backend_kind=FILESYSTEM, root=str(base)), base


@pytest.fixture
def object_boundary():
    return ScopeBoundary(backend_kind=OBJECT_STORE, root="acme-data", prefix="reports")


# --------------------------------------------------------------------------- #
# AC-01 -- relative traversal
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("payload", ["../secret.txt", "../../etc/passwd", "a/../../secret.txt", "a/b/../../../secret"])
def test_ac01_relative_traversal_is_denied_filesystem(fs_boundary, payload):
    boundary, _ = fs_boundary
    with pytest.raises(ScopeViolationError):
        resolve_and_contain(boundary, payload)


@pytest.mark.parametrize("payload", ["../secret.txt", "../../secret", "a/../../../etc/passwd"])
def test_ac01_relative_traversal_is_denied_object_store(object_boundary, payload):
    with pytest.raises(ScopeViolationError):
        resolve_and_contain(object_boundary, payload)


# --------------------------------------------------------------------------- #
# AC-02 -- absolute paths
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("payload", ["/etc/passwd", "C:\\Windows\\system32\\config", "\\\\server\\share\\file", "D:/secrets"])
def test_ac02_absolute_paths_are_denied(fs_boundary, payload):
    boundary, _ = fs_boundary
    with pytest.raises(ScopeViolationError):
        resolve_and_contain(boundary, payload)


def test_ac02_absolute_paths_are_denied_object_store(object_boundary):
    with pytest.raises(ScopeViolationError):
        resolve_and_contain(object_boundary, "/etc/passwd")


# --------------------------------------------------------------------------- #
# AC-03 -- percent-encoded traversal
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("payload", ["%2e%2e%2fsecret.txt", "%2e%2e/secret.txt", "..%2fsecret.txt", "%2e%2e%2f%2e%2e%2fsecret"])
def test_ac03_percent_encoded_traversal_is_denied(fs_boundary, payload):
    boundary, _ = fs_boundary
    with pytest.raises(ScopeViolationError):
        resolve_and_contain(boundary, payload)


# --------------------------------------------------------------------------- #
# AC-04 -- double-encoded traversal
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("payload", ["..%252fsecret.txt", "..%252f..%252fsecret.txt", "%252e%252e%252fsecret"])
def test_ac04_double_encoded_traversal_is_denied(fs_boundary, payload):
    boundary, _ = fs_boundary
    with pytest.raises(ScopeViolationError):
        resolve_and_contain(boundary, payload)


# --------------------------------------------------------------------------- #
# AC-05 -- backslash variants
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("payload", ["..\\secret.txt", "..\\..\\secret.txt", "a\\..\\..\\secret", "..\\/secret.txt"])
def test_ac05_backslash_traversal_variants_are_denied(fs_boundary, payload):
    boundary, _ = fs_boundary
    with pytest.raises(ScopeViolationError):
        resolve_and_contain(boundary, payload)


# --------------------------------------------------------------------------- #
# AC-06 -- null-byte / control-char truncation, literal and encoded
# --------------------------------------------------------------------------- #
def test_ac06_literal_null_byte_is_denied(fs_boundary):
    boundary, _ = fs_boundary
    with pytest.raises(ScopeViolationError):
        resolve_and_contain(boundary, "file.txt\x00.png")


def test_ac06_percent_encoded_null_byte_is_denied(fs_boundary):
    boundary, _ = fs_boundary
    with pytest.raises(ScopeViolationError):
        resolve_and_contain(boundary, "file.txt%00.png")


def test_ac06_other_control_characters_are_denied(fs_boundary):
    boundary, _ = fs_boundary
    with pytest.raises(ScopeViolationError):
        resolve_and_contain(boundary, "file\x1b[31m.txt")


# --------------------------------------------------------------------------- #
# AC-07 -- unicode normalization / homoglyph tricks resolving to ".."
# --------------------------------------------------------------------------- #
def test_ac07_fullwidth_unicode_dot_slash_normalizes_and_is_denied(fs_boundary):
    """Fullwidth ideographic full stop (U+FF0E) and fullwidth solidus
    (U+FF0F) NFKC-normalize to ASCII '.' and '/' respectively -- a
    homoglyph traversal attempt that would slip past a naive
    ``".." in raw_string`` check is caught only because canonicalization
    (NFKC) runs before the traversal check does."""
    boundary, _ = fs_boundary
    payload = "．．／secret.txt"  # "．．／secret.txt"
    with pytest.raises(ScopeViolationError):
        resolve_and_contain(boundary, payload)


def test_ac07_invalid_percent_encoded_utf8_is_denied_fail_closed(fs_boundary):
    """An invalid UTF-8 byte sequence smuggled in as percent-encoding
    (e.g. an overlong/malformed continuation byte) is denied outright
    rather than silently decoded with a lossy replacement character,
    which could otherwise mask what the raw bytes actually meant."""
    boundary, _ = fs_boundary
    with pytest.raises(ScopeViolationError):
        resolve_and_contain(boundary, "%e2%28%a1secret.txt")


# --------------------------------------------------------------------------- #
# AC-08 -- object-store key normalizing outside its declared prefix
# --------------------------------------------------------------------------- #
def test_ac08_key_normalizing_outside_prefix_is_denied(object_boundary):
    with pytest.raises(ScopeViolationError):
        resolve_and_contain(object_boundary, "../secrets/config.json")


def test_ac08_key_normalizing_outside_bucket_entirely_is_denied(object_boundary):
    with pytest.raises(ScopeViolationError):
        resolve_and_contain(object_boundary, "../../../etc/passwd")


def test_ac08_sibling_prefix_is_not_treated_as_contained():
    """A naive ``str.startswith(prefix)`` check would wrongly let
    ``"reports-2/x"`` pass for a declared prefix of ``"reports"`` --
    containment must respect the ``/`` segment boundary."""
    boundary = ScopeBoundary(backend_kind=OBJECT_STORE, root="acme-data", prefix="reports")
    with pytest.raises(ScopeViolationError):
        resolve_and_contain(boundary, "../reports-2/x")


def test_ac08_a_key_within_the_declared_prefix_succeeds(object_boundary):
    target = resolve_and_contain(object_boundary, "q1/summary.txt")
    assert target.resolved_path == "reports/q1/summary.txt"
    assert target.relative_path == "q1/summary.txt"


def test_ac08_a_key_with_no_declared_prefix_stays_within_the_whole_bucket():
    boundary = ScopeBoundary(backend_kind=OBJECT_STORE, root="acme-data", prefix="")
    target = resolve_and_contain(boundary, "any/where.json")
    assert target.resolved_path == "any/where.json"
    with pytest.raises(ScopeViolationError):
        resolve_and_contain(boundary, "../outside-the-bucket")


# --------------------------------------------------------------------------- #
# AC-09 -- filesystem symlink escape, real temp symlink
# --------------------------------------------------------------------------- #
def _make_link(link_path: str, target_dir: str) -> bool:
    """Creates a real symlink (POSIX, or Windows with the privilege) or
    falls back to a directory junction on Windows (no elevated privilege
    required, and — like a symlink — resolved by ``os.path.realpath``).
    Returns True if a link was actually created."""
    try:
        os.symlink(target_dir, link_path, target_is_directory=True)
        return True
    except OSError:
        pass
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", link_path, target_dir], capture_output=True, text=True,
        )
        return result.returncode == 0
    return False


def test_ac09_symlink_inside_scope_pointing_outside_is_denied_after_realpath_resolution(tmp_path):
    scope_root = tmp_path / "scope"
    scope_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("do-not-read", encoding="utf-8")

    link_path = str(scope_root / "escape_link")
    if not _make_link(link_path, str(outside)):
        pytest.skip("this host cannot create a symlink or junction without elevated privileges")

    boundary = ScopeBoundary(backend_kind=FILESYSTEM, root=str(scope_root))
    with pytest.raises(ScopeViolationError):
        resolve_and_contain(boundary, "escape_link/secret.txt")


# --------------------------------------------------------------------------- #
# AC-10 -- canonicalize then contain; the validated path, not the raw
# string, is what a caller would act on (no TOCTOU gap)
# --------------------------------------------------------------------------- #
def test_ac10_the_validated_target_is_the_canonical_resolved_form_not_the_raw_input(fs_boundary):
    boundary, base = fs_boundary
    nested = base / "a" / "b"
    nested.mkdir(parents=True)
    (nested / "file.txt").write_text("x", encoding="utf-8")

    target = resolve_and_contain(boundary, "a/./b/../b/file.txt")
    assert target.relative_path == "a/b/file.txt"
    assert target.resolved_path == str((base / "a" / "b" / "file.txt").resolve())


def test_ac10_a_denied_path_never_yields_a_validated_target(fs_boundary):
    boundary, _ = fs_boundary
    with pytest.raises(ScopeViolationError) as excinfo:
        resolve_and_contain(boundary, "../secret.txt")
    # the exception carries no target/resolved-path attribute a caller
    # could mistakenly treat as safe to use anyway
    assert not hasattr(excinfo.value, "resolved_path")


# --------------------------------------------------------------------------- #
# AC-11 -- exercised entirely without live storage (this whole file)
# --------------------------------------------------------------------------- #
def test_ac11_this_module_has_no_dependency_on_a_live_backend():
    import ast
    from pathlib import Path

    tree = ast.parse(Path(__file__).resolve().parents[2].joinpath(
        "app", "integration", "connectors", "storage", "scope.py"
    ).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
    # stdlib only -- no boto3, no sqlalchemy, no app.* platform module.
    assert imported <= {"os", "posixpath", "re", "unicodedata", "urllib", "dataclasses", "__future__"}


# --------------------------------------------------------------------------- #
# Plain valid-path sanity (not itself an AC, but establishes the enforcer
# permits ordinary, legitimate access -- a defense that denies everything
# would trivially "pass" every denial test above for the wrong reason)
# --------------------------------------------------------------------------- #
def test_a_legitimate_nested_path_is_permitted(fs_boundary):
    boundary, base = fs_boundary
    (base / "reports").mkdir()
    (base / "reports" / "q1.txt").write_text("hi", encoding="utf-8")
    target = resolve_and_contain(boundary, "reports/q1.txt")
    assert target.relative_path == "reports/q1.txt"
    assert os.path.isfile(target.resolved_path)


def test_root_itself_is_a_valid_target(fs_boundary):
    boundary, base = fs_boundary
    target = resolve_and_contain(boundary, ".")
    assert target.relative_path == ""
    assert target.resolved_path == str(base.resolve())


def test_empty_or_non_string_supplied_path_is_denied(fs_boundary):
    boundary, _ = fs_boundary
    with pytest.raises(ScopeViolationError):
        resolve_and_contain(boundary, "")
    with pytest.raises(ScopeViolationError):
        resolve_and_contain(boundary, None)  # type: ignore[arg-type]


def test_ntfs_alternate_data_stream_colon_is_denied(fs_boundary):
    boundary, _ = fs_boundary
    with pytest.raises(ScopeViolationError):
        resolve_and_contain(boundary, "file.txt:hidden_stream")
