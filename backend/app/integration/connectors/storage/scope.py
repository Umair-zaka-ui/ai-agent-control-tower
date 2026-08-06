"""Phase 2.2.3 SRS ACT-INT-FR-141, FR-143 — the traversal/scope-escape
enforcer. This is the security-critical module: the storage analogue of
Milestone 1's isolated egress guard, and of 2.2.2's ``executor.py``.

**The contract.** ``resolve_and_contain(boundary, supplied_path)`` takes a
declared ``ScopeBoundary`` (a filesystem base directory, or an
object-store bucket + optional key prefix) and a model-supplied path/key
fragment, and returns a ``ValidatedTarget`` — or raises
``ScopeViolationError``. There is no function anywhere in this module
that performs a read, a write, or any I/O against a real store; it has no
dependency on ``app.integration.errors``, the SDK, a database session, or
any platform service — pure stdlib, importable and testable in complete
isolation, exactly as the build prompt's own §6 requires ("built and
tested in isolation... every traversal vector is tested without a
backend").

**Canonicalize, then contain — never the reverse.** Every call performs
the same four-stage pipeline before any backend-specific logic runs:

1. Reject control characters (including a literal NUL) in the raw input.
2. Percent-decode iteratively (bounded rounds) so single- and
   double-encoded traversal sequences (``%2e%2e%2f``, ``..%252f``) are
   revealed before any check runs against them — checking the raw string
   and only *then* decoding would let an encoded ``..`` slip past a check
   that only ever saw the encoded form.
3. Reject any control character revealed by decoding (catches an
   encoded NUL, ``file.txt%00.png``).
4. Unicode-normalize (NFKC) so a homoglyph/fullwidth variant of ``.`` or
   ``/`` (e.g. U+FF0E, U+FF0F) collapses to its canonical ASCII form
   before the traversal check runs, rather than slipping through as a
   character a naive ``".." in path`` check would not recognize.

Only *after* that pipeline does backend-specific canonicalization run —
``os.path.realpath`` (resolving both ``..`` and symlinks) for the
filesystem backend, ``posixpath.normpath`` (lexical only — object
storage has no real filesystem to resolve against) for object storage —
and only the *canonicalized* result is ever contained-checked or
returned as the operation's real target. The raw or partially-processed
string is never used for anything but producing that canonical form —
the "resolve, then contain, and use only what was resolved" discipline
that closes the TOCTOU/rebinding-shaped gap the build prompt calls out
explicitly (§4.2, AC-10)."""

from __future__ import annotations

import os
import posixpath
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass

FILESYSTEM = "FILESYSTEM"
OBJECT_STORE = "OBJECT_STORE"
_BACKEND_KINDS = frozenset({FILESYSTEM, OBJECT_STORE})

_DRIVE_ABSOLUTE_RE = re.compile(r"^[a-zA-Z]:[\\/]")
_MAX_DECODE_ROUNDS = 6


class ScopeViolationError(Exception):
    """A supplied path/key could not be proven to resolve inside its
    declared scope. The message never includes the declared scope's own
    absolute root/bucket value or the raw supplied input — only a safe,
    generic description of which check failed — so a denial can be
    logged or returned to a caller without itself leaking the boundary
    it protects."""


@dataclass(frozen=True, slots=True)
class ScopeBoundary:
    """One declared scope, translated from ``declaration.py``'s own
    connector-facing shape into the two things enforcement actually
    needs: which canonicalization rules apply (``backend_kind``), and
    what a resolved target must stay inside (``root`` — an absolute base
    directory for ``FILESYSTEM``, a bucket/container name for
    ``OBJECT_STORE``; ``prefix`` — object storage only, ``""`` for
    "the whole bucket is in scope")."""

    backend_kind: str
    root: str
    prefix: str = ""

    def __post_init__(self) -> None:
        if self.backend_kind not in _BACKEND_KINDS:
            raise ValueError(f"unknown backend_kind '{self.backend_kind}'")


@dataclass(frozen=True, slots=True)
class ValidatedTarget:
    """The outcome of a successful ``resolve_and_contain`` call — the
    *only* thing a backend may ever use to perform a real operation.
    ``relative_path`` is scope-relative and safe to log/audit (never an
    absolute host path, never a value that escaped its boundary).
    ``resolved_path`` is what the backend actually acts on: a real
    (symlink-resolved) absolute filesystem path, or a full object-store
    key relative to the bucket."""

    relative_path: str
    resolved_path: str


def _reject_control_chars(value: str) -> None:
    for ch in value:
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            raise ScopeViolationError("path contains a control character")


def _iterative_percent_decode(value: str) -> str:
    current = value
    for _ in range(_MAX_DECODE_ROUNDS):
        try:
            decoded = urllib.parse.unquote(current, errors="strict")
        except UnicodeDecodeError as exc:
            raise ScopeViolationError("path contains an invalid percent-encoded sequence") from exc
        if decoded == current:
            return decoded
        current = decoded
    return current


def _looks_absolute(value: str) -> bool:
    return value.startswith("/") or value.startswith("\\") or bool(_DRIVE_ABSOLUTE_RE.match(value))


def _canonicalize(supplied_path: str) -> str:
    if not isinstance(supplied_path, str) or not supplied_path:
        raise ScopeViolationError("a non-empty path is required")
    _reject_control_chars(supplied_path)
    decoded = _iterative_percent_decode(supplied_path)
    _reject_control_chars(decoded)
    normalized = unicodedata.normalize("NFKC", decoded)
    if _looks_absolute(normalized):
        raise ScopeViolationError("absolute paths are not permitted")
    return normalized


def _resolve_filesystem(boundary: ScopeBoundary, normalized: str) -> ValidatedTarget:
    # ':' is never valid inside a relative filesystem fragment we accept:
    # it either marks a Windows drive letter (an absolute path our string-
    # level check could miss if embedded mid-path, e.g. "docs/C:/evil") or
    # an NTFS alternate-data-stream name ("file.txt:hidden") — both denied
    # outright rather than pattern-matched, since neither has a legitimate
    # use for a scoped object name.
    if ":" in normalized:
        raise ScopeViolationError("path contains a disallowed character")
    segments = [segment for segment in normalized.replace("\\", "/").split("/")]
    base_real = os.path.realpath(boundary.root)
    joined = os.path.join(boundary.root, *segments) if segments else boundary.root
    real_candidate = os.path.realpath(joined)
    if real_candidate != base_real and not real_candidate.startswith(base_real + os.sep):
        raise ScopeViolationError("resolved path escapes its declared base directory")
    relative_path = os.path.relpath(real_candidate, base_real).replace(os.sep, "/")
    if relative_path == ".":
        relative_path = ""
    return ValidatedTarget(relative_path=relative_path, resolved_path=real_candidate)


def _resolve_object_store(boundary: ScopeBoundary, normalized: str) -> ValidatedTarget:
    prefix = boundary.prefix.strip("/")
    supplied = normalized.strip("/")
    combined = f"{prefix}/{supplied}" if prefix else supplied
    resolved = posixpath.normpath(combined) if combined else ""
    if resolved == ".":
        resolved = ""
    if resolved == ".." or resolved.startswith("../"):
        raise ScopeViolationError("resolved key escapes the declared bucket")
    if prefix:
        if resolved != prefix and not resolved.startswith(prefix + "/"):
            raise ScopeViolationError("resolved key escapes its declared prefix")
        relative_path = resolved[len(prefix):].lstrip("/")
    else:
        relative_path = resolved
    return ValidatedTarget(relative_path=relative_path, resolved_path=resolved)


def resolve_and_contain(boundary: ScopeBoundary, supplied_path: str) -> ValidatedTarget:
    """The one, only, public entry point. Canonicalizes ``supplied_path``
    (percent-decoding, Unicode-normalizing, and rejecting anything
    absolute or control-character-bearing) and then applies
    backend-specific canonicalize-and-contain — ``os.path.realpath``
    (resolves ``..`` *and* symlinks) for ``FILESYSTEM``,
    ``posixpath.normpath`` (lexical, no filesystem I/O) for
    ``OBJECT_STORE``. Raises ``ScopeViolationError`` for anything that
    cannot be proven to resolve inside ``boundary`` — never truncates,
    strips, or "best-effort sanitizes" a value that would otherwise
    escape."""
    normalized = _canonicalize(supplied_path)
    if boundary.backend_kind == FILESYSTEM:
        return _resolve_filesystem(boundary, normalized)
    return _resolve_object_store(boundary, normalized)
