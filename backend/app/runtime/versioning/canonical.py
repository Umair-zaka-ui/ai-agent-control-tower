"""Phase 5.2.4 SRS ACT-VER-FR-025, FR-040..FR-047 — canonical serialization.

The single source of truth for turning a Python object into the exact bytes
that get hashed and signed. Every producer and every verifier, now and in
any future language, must agree on these bytes — a signature over a
non-reproducible digest is worthless: the moment an external auditor (or a
second implementation in another language) recomputes the digest with a
different serialization, verification fails on an artifact that was never
tampered with, and the failure is silent and looks like tampering.

Rules, all mandatory, applied recursively at every depth (a second-language
implementation of this exact rule set must reproduce every one of these,
not just "compact JSON"):

- **Key ordering**: lexicographic by Unicode code point. Python's own
  string comparison already orders by code point, so ``sort_keys=True``
  on the NFC-normalized structure below satisfies this directly.
- **Unicode normalization**: NFC, applied to every string key and string
  value before comparison/serialization.
- **Encoding**: UTF-8, no BOM.
- **Whitespace**: none — ``,`` and ``:`` separators exactly, no spaces,
  no newlines.
- **Non-ASCII**: emitted literally (``ensure_ascii=False``), never
  ``\\uXXXX``-escaped.
- **Floats**: rejected outright. IEEE-754 floats do not round-trip
  reliably across JSON encoders/languages — ``0.1 + 0.2`` serializes
  differently in Python, Go, and JavaScript — so a digest over a raw float
  is not portable. ``canonicalize()``/``digest()`` raise
  ``CanonicalizationError`` the moment one is encountered anywhere in the
  structure; callers with known float fields (e.g.
  ``model_configuration.temperature``) must convert them explicitly first
  — see ``stringify_floats()`` below. This is a deliberate asymmetry: the
  canonicalizer itself never silently guesses a float's portable
  representation, since that guess is exactly the kind of hidden,
  language-specific behavior this module exists to eliminate. The
  conversion is instead an explicit, documented, opt-in step the *producer*
  takes before handing data to this module.
- **Integers**: emitted without leading zeros or a ``+`` sign — already
  the case for every Python ``int``, asserted defensively rather than
  actively enforced (there is no Python int literal that violates this).
- **Booleans / null**: ``true``, ``false``, ``null``.
- **Nested containers**: every rule above applies recursively; lists
  preserve order (only object keys are sorted — JSON arrays are ordered by
  definition and reordering them would change their meaning).

Unsupported types (anything not ``None``/``bool``/``int``/``str``/``dict``/
``list``/``tuple``) also raise ``CanonicalizationError`` rather than being
silently stringified — this is why ``_checksum()``/``checksum_of()`` had to
be fixed to pass already-portable values (ISO-8601 date strings, not raw
``datetime`` objects) rather than relying on ``json.dumps(..., default=str)``
as they did before this phase; see ``docs/runtime/versioning.md``'s Phase
5.2.4 section for what that surfaced.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import unicodedata
from typing import Any


class CanonicalizationError(Exception):
    """Raised when an object cannot be canonicalized — a float anywhere in
    the structure, or a value of an unsupported type."""


def _normalize_str(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _canonicalize(obj: Any) -> Any:
    """Recursively normalizes ``obj`` into a structure ``json.dumps`` can
    render deterministically — NFC-normalized string keys/values, floats
    and unsupported types rejected, dict/list/tuple recursed into. Returns
    a new structure; never mutates the input."""
    if isinstance(obj, bool):
        return obj  # bool is an int subclass in Python; check before int.
    if isinstance(obj, float):
        raise CanonicalizationError(
            f"Cannot canonicalize a float ({obj!r}) — IEEE-754 floats do not round-trip "
            "reliably across languages/encoders. Convert to a string or integer first "
            "(see canonical.stringify_floats())."
        )
    if isinstance(obj, int):
        return obj
    if obj is None:
        return None
    if isinstance(obj, str):
        return _normalize_str(obj)
    if isinstance(obj, dict):
        return {(_normalize_str(k) if isinstance(k, str) else k): _canonicalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_canonicalize(item) for item in obj]
    raise CanonicalizationError(f"Cannot canonicalize a value of unsupported type {type(obj).__name__!r}: {obj!r}")


def canonicalize(obj: Any) -> bytes:
    """Returns the canonical byte serialization of ``obj``. Raises
    ``CanonicalizationError`` on any float or unsupported type anywhere in
    the structure."""
    normalized = _canonicalize(obj)
    text = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return text.encode("utf-8")


def digest_bytes(data: bytes) -> str:
    """``sha256:<64 lowercase hex>`` of raw bytes — algorithm-prefixed
    (``ACT-VER-FR-041``) so a future second algorithm doesn't need a format
    migration, only a different prefix."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def digest(obj: Any) -> str:
    """``sha256:<64 lowercase hex>`` of ``canonicalize(obj)``."""
    return digest_bytes(canonicalize(obj))


def verify_digest(obj: Any, expected: str) -> bool:
    """Constant-time comparison of ``digest(obj)`` against an expected
    ``sha256:...`` digest string."""
    return hmac.compare_digest(digest(obj), expected)


def stringify_floats(obj: Any) -> Any:
    """Recursively converts every float leaf to its ``str()`` representation
    — the documented, deterministic escape hatch for producers who know
    their data contains floats (e.g. ``model_configuration.temperature``,
    ``model_configuration.top_p``) and want them hashed reproducibly rather
    than raising. Does not mutate ``obj``; returns a new structure.
    Booleans are checked first since ``bool`` is an ``int`` subclass in
    Python and must never be treated as numeric here."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return str(obj)
    if isinstance(obj, dict):
        return {k: stringify_floats(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [stringify_floats(item) for item in obj]
    return obj
