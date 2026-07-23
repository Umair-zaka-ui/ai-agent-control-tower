"""Phase 5.2.4 tests — canonical serialization (``canonical.py``).

Entirely database-free — every test here calls the pure module functions
directly with plain Python objects. See ``test_version_signing.py`` and
``test_attestation.py`` for the integration/API layers built on top of this.
"""

from __future__ import annotations

import unicodedata

import pytest

from app.runtime.versioning import canonical

# --------------------------------------------------------------------------- #
# Known-answer vectors — also published in docs/runtime/versioning.md's
# Phase 5.2.4 section, so a second-language implementation of canonical.py's
# rules can check its own output against the same fixed inputs/outputs.
# --------------------------------------------------------------------------- #
KNOWN_ANSWER_VECTORS = [
    ("empty_object", {}, "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"),
    ("empty_array", [], "sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"),
    ("null_value", None, "sha256:74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b"),
    ("simple_object", {"a": 1, "b": "two", "c": True, "d": None},
     "sha256:eb2c149467b56cfad324e3c07e2eb850f0481017871fe2250e3d21c9d0ba1fdc"),
    ("nested_object", {"outer": {"z": 1, "a": [3, 2, 1]}, "flag": False},
     "sha256:f9de48f91c5f237ea969b03b9d8c8dabf4bf81d9353800ce3840afcb2167e49a"),
    ("unicode_object", {"name": "héllo wörld 🎉"},
     "sha256:3af931f0fc2a91cbcfcd909e0d2b0962c43b0a7a1cdef759a8767d16392508c1"),
]


@pytest.mark.parametrize("name,value,expected_digest", KNOWN_ANSWER_VECTORS, ids=[v[0] for v in KNOWN_ANSWER_VECTORS])
def test_known_answer_vectors_produce_exactly_the_expected_digest(name, value, expected_digest) -> None:
    """AC-08."""
    assert canonical.digest(value) == expected_digest


def test_key_order_independence_produces_identical_bytes() -> None:
    """AC-01."""
    assert canonical.canonicalize({"b": 1, "a": 2}) == canonical.canonicalize({"a": 2, "b": 1})


def test_nested_dicts_sorted_recursively_at_every_depth() -> None:
    """AC-02."""
    a = canonical.canonicalize({"outer": {"z": 1, "a": 2}, "top": 1})
    b = canonical.canonicalize({"top": 1, "outer": {"a": 2, "z": 1}})
    assert a == b
    assert a == b'{"outer":{"a":2,"z":1},"top":1}'


def test_nfd_and_nfc_unicode_forms_produce_identical_bytes() -> None:
    """AC-03."""
    nfc = unicodedata.normalize("NFC", "café")
    nfd = unicodedata.normalize("NFD", "café")
    assert nfc != nfd  # sanity: these really are different byte sequences pre-normalization
    assert canonical.canonicalize({"name": nfc}) == canonical.canonicalize({"name": nfd})


def test_output_has_no_whitespace_between_tokens() -> None:
    """AC-04."""
    output = canonical.canonicalize({"a": [1, 2, 3], "b": "x", "c": {"d": 1}})
    assert b" " not in output
    assert b"\n" not in output
    assert b"\t" not in output


def test_non_ascii_emitted_literally_not_escaped() -> None:
    """AC-05."""
    output = canonical.canonicalize({"emoji": "🎉", "name": "héllo"})
    assert "\\u" not in output.decode("utf-8")
    assert "🎉".encode("utf-8") in output


def test_float_anywhere_in_structure_raises() -> None:
    """AC-06."""
    with pytest.raises(canonical.CanonicalizationError):
        canonical.canonicalize({"a": 1.5})
    with pytest.raises(canonical.CanonicalizationError):
        canonical.canonicalize({"nested": {"list": [1, 2.0, 3]}})
    with pytest.raises(canonical.CanonicalizationError):
        canonical.canonicalize([0.1, 0.2])


def test_digest_format_is_sha256_prefixed_64_hex() -> None:
    """AC-07."""
    result = canonical.digest({"a": 1})
    assert result.startswith("sha256:")
    hex_part = result.split(":", 1)[1]
    assert len(hex_part) == 64
    assert all(c in "0123456789abcdef" for c in hex_part)


def test_serializing_same_object_1000_times_is_always_identical() -> None:
    """AC-09."""
    obj = {"a": 1, "b": [1, 2, 3], "c": {"nested": True, "z": None}, "d": "text"}
    results = {canonical.digest(obj) for _ in range(1000)}
    assert len(results) == 1


def test_empty_containers_and_null_serialize_deterministically() -> None:
    """AC-10."""
    assert canonical.canonicalize({}) == b"{}"
    assert canonical.canonicalize([]) == b"[]"
    assert canonical.canonicalize(None) == b"null"


def test_integers_have_no_leading_zeros_or_plus_sign() -> None:
    output = canonical.canonicalize({"a": 5, "b": -3, "c": 0})
    assert output == b'{"a":5,"b":-3,"c":0}'


def test_verify_digest_constant_time_comparison() -> None:
    obj = {"a": 1}
    assert canonical.verify_digest(obj, canonical.digest(obj)) is True
    assert canonical.verify_digest(obj, "sha256:" + "0" * 64) is False


def test_stringify_floats_converts_leaves_without_mutating_input() -> None:
    original = {"temperature": 0.9, "nested": {"top_p": 0.1}, "count": 5, "flag": True}
    converted = canonical.stringify_floats(original)
    assert converted == {"temperature": "0.9", "nested": {"top_p": "0.1"}, "count": 5, "flag": True}
    assert original["temperature"] == 0.9  # not mutated
    # And the converted structure is now canonicalizable where the original was not.
    with pytest.raises(canonical.CanonicalizationError):
        canonical.canonicalize(original)
    canonical.digest(converted)  # does not raise


def test_unsupported_type_raises_rather_than_silently_stringifying() -> None:
    class Unsupported:
        pass

    with pytest.raises(canonical.CanonicalizationError):
        canonical.canonicalize({"x": Unsupported()})
