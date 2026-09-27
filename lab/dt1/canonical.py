"""Canonical serialization, content hashing and stable identifiers (§7, §8).

* ``canonical_bytes``: UTF-8 JSON, sorted keys, compact separators, ``\\n`` line
  ending, trailing newline, ``allow_nan=False``. Lists are emitted in the order
  the generator built them, and the generator always sorts entity lists by
  their stable id before serialization (``sort_entities``).
* ``stable_id``: ``prefix-`` + first 20 hex chars of
  ``SHA-256(seed | kind | natural_key)``; never random, never time-based.
* ``stable_uuid``: a UUID-shaped rendering of the same digest (version nibble
  forced to 5-style ``5``, variant ``8``) for fields that are UUID-typed in ACT.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_ID_RE = re.compile(r"^[a-z0-9]{2,6}-[0-9a-f]{20}$")


def canonical_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash(obj: Any) -> str:
    return sha256_hex(canonical_bytes(obj))


def stable_id(seed: str, kind: str, natural_key: str) -> str:
    digest = hashlib.sha256(f"{seed}|{kind}|{natural_key}".encode("utf-8")).hexdigest()
    return f"{kind}-{digest[:20]}"


def stable_uuid(seed: str, kind: str, natural_key: str) -> str:
    h = hashlib.sha256(f"{seed}|uuid|{kind}|{natural_key}".encode("utf-8")).hexdigest()
    return f"{h[:8]}-{h[8:12]}-5{h[13:16]}-8{h[17:20]}-{h[20:32]}"


def is_stable_id(value: str) -> bool:
    return bool(_ID_RE.match(value or ""))


def sort_entities(items: list[dict], key: str = "id") -> list[dict]:
    return sorted(items, key=lambda d: d[key])
