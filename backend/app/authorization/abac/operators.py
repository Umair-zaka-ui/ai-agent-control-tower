"""ABAC operator registry (Phase 4.3.5 §9, §10, §24).

Every policy operator maps to a small, safe Python function — dynamic code
execution is prohibited (§40.2); only operators registered here are allowed
(§40.3). Type validation rejects nonsense comparisons (``risk_score > "high"``)
at policy-validation time (§10), and the regex operator is guarded against
catastrophic patterns (§42 security tests).
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from typing import Any, Callable

from app.authorization.abac.enums import AttributeDataType, Operator

# --------------------------------------------------------------------------- #
# Regex safety (§40, §42) — a policy regex must be short, compilable and free
# of the nested-quantifier shapes that make Python's backtracking engine
# explode (e.g. ``(a+)+$``); evaluated input is capped as a second layer.
# --------------------------------------------------------------------------- #
MAX_REGEX_LENGTH = 256
MAX_REGEX_INPUT_LENGTH = 4096
_NESTED_QUANTIFIER = re.compile(r"\([^()]*[*+][^()]*\)\s*[*+{]")


def validate_regex_pattern(pattern: str) -> str | None:
    """Return an error message if the pattern is unsafe/invalid, else None."""
    if not isinstance(pattern, str):
        return "Regex pattern must be a string."
    if len(pattern) > MAX_REGEX_LENGTH:
        return f"Regex pattern longer than {MAX_REGEX_LENGTH} characters."
    if _NESTED_QUANTIFIER.search(pattern):
        return "Regex pattern contains a nested quantifier (ReDoS risk)."
    try:
        re.compile(pattern)
    except re.error as exc:
        return f"Invalid regex pattern: {exc}"
    return None


# --------------------------------------------------------------------------- #
# Comparison helpers
# --------------------------------------------------------------------------- #
_ISO_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ].+)?$")


def _coerce_pair(actual: Any, expected: Any) -> tuple[Any, Any]:
    """Best-effort coercion so ordered comparisons work across the supported
    types: numbers compare as floats, ISO datetime/date strings as datetimes."""
    if isinstance(actual, bool) or isinstance(expected, bool):
        return actual, expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return float(actual), float(expected)
    if isinstance(actual, (datetime, date, time)) or isinstance(expected, (datetime, date, time)):
        return _to_dt(actual), _to_dt(expected)
    if (isinstance(actual, str) and isinstance(expected, str)
            and _ISO_LIKE.match(actual) and _ISO_LIKE.match(expected)):
        return _to_dt(actual), _to_dt(expected)
    return actual, expected


def _to_dt(value: Any) -> Any:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value


def _ordered(op: Callable[[Any, Any], bool]) -> Callable[[Any, Any], bool]:
    def compare(actual: Any, expected: Any) -> bool:
        a, e = _coerce_pair(actual, expected)
        try:
            return op(a, e)
        except TypeError:
            return False
    return compare


def _contains(actual: Any, expected: Any) -> bool:
    if isinstance(actual, str) and isinstance(expected, str):
        return expected in actual
    if isinstance(actual, (list, tuple, set)):
        return expected in actual
    return False


def _matches_regex(actual: Any, expected: Any) -> bool:
    if not isinstance(actual, str) or not isinstance(expected, str):
        return False
    if validate_regex_pattern(expected) is not None:
        return False  # never run an unsafe pattern, even if one slipped through
    return re.search(expected, actual[:MAX_REGEX_INPUT_LENGTH]) is not None


def _between(actual: Any, expected: Any) -> bool:
    if not isinstance(expected, (list, tuple)) or len(expected) != 2:
        return False
    low_ok = _ordered(lambda a, e: a >= e)(actual, expected[0])
    high_ok = _ordered(lambda a, e: a <= e)(actual, expected[1])
    return low_ok and high_ok


class OperatorRegistry:
    """§24 — maps policy operators to safe implementations. ``EXISTS`` /
    ``NOT_EXISTS`` are resolved by the condition evaluator (they act on
    attribute *presence*, not value)."""

    _FUNCTIONS: dict[str, Callable[[Any, Any], bool]] = {
        Operator.EQUALS.value: lambda a, e: _coerce_pair(a, e)[0] == _coerce_pair(a, e)[1],
        Operator.NOT_EQUALS.value: lambda a, e: _coerce_pair(a, e)[0] != _coerce_pair(a, e)[1],
        Operator.IN.value: lambda a, e: isinstance(e, (list, tuple, set)) and a in e,
        Operator.NOT_IN.value: lambda a, e: isinstance(e, (list, tuple, set)) and a not in e,
        Operator.CONTAINS.value: _contains,
        Operator.NOT_CONTAINS.value: lambda a, e: not _contains(a, e),
        Operator.GREATER_THAN.value: _ordered(lambda a, e: a > e),
        Operator.GREATER_THAN_OR_EQUAL.value: _ordered(lambda a, e: a >= e),
        Operator.LESS_THAN.value: _ordered(lambda a, e: a < e),
        Operator.LESS_THAN_OR_EQUAL.value: _ordered(lambda a, e: a <= e),
        Operator.STARTS_WITH.value: lambda a, e: isinstance(a, str) and isinstance(e, str) and a.startswith(e),
        Operator.ENDS_WITH.value: lambda a, e: isinstance(a, str) and isinstance(e, str) and a.endswith(e),
        Operator.MATCHES_REGEX.value: _matches_regex,
        Operator.BETWEEN.value: _between,
    }

    @classmethod
    def is_registered(cls, operator: str) -> bool:
        return operator in cls._FUNCTIONS or operator in (
            Operator.EXISTS.value, Operator.NOT_EXISTS.value
        )

    @classmethod
    def apply(cls, operator: str, actual: Any, expected: Any) -> bool:
        fn = cls._FUNCTIONS.get(operator)
        if fn is None:
            return False  # unregistered operators never match (§40.3)
        return bool(fn(actual, expected))


# --------------------------------------------------------------------------- #
# Value/type validation (§10) — at policy validation time
# --------------------------------------------------------------------------- #
_ORDERED_OPERATORS = {
    Operator.GREATER_THAN.value, Operator.GREATER_THAN_OR_EQUAL.value,
    Operator.LESS_THAN.value, Operator.LESS_THAN_OR_EQUAL.value, Operator.BETWEEN.value,
}
_STRING_OPERATORS = {
    Operator.STARTS_WITH.value, Operator.ENDS_WITH.value, Operator.MATCHES_REGEX.value,
}
_LIST_VALUE_OPERATORS = {Operator.IN.value, Operator.NOT_IN.value}
_NO_VALUE_OPERATORS = {Operator.EXISTS.value, Operator.NOT_EXISTS.value}
_ORDERABLE_TYPES = {
    AttributeDataType.INTEGER.value, AttributeDataType.DECIMAL.value,
    AttributeDataType.DATETIME.value, AttributeDataType.DATE.value,
    AttributeDataType.TIME.value, AttributeDataType.STRING.value,
}


def _scalar_matches_type(value: Any, data_type: str) -> bool:
    if data_type == AttributeDataType.STRING.value:
        return isinstance(value, str)
    if data_type == AttributeDataType.INTEGER.value:
        return isinstance(value, int) and not isinstance(value, bool)
    if data_type == AttributeDataType.DECIMAL.value:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if data_type == AttributeDataType.BOOLEAN.value:
        return isinstance(value, bool)
    if data_type in (AttributeDataType.DATETIME.value, AttributeDataType.DATE.value,
                     AttributeDataType.TIME.value):
        return isinstance(value, str)  # ISO strings in JSON policies
    if data_type in (AttributeDataType.ARRAY.value, AttributeDataType.SET.value):
        return isinstance(value, list)
    if data_type == AttributeDataType.OBJECT.value:
        return isinstance(value, dict)
    if data_type == AttributeDataType.NULL.value:
        return value is None
    return False


def validate_condition_value(operator: str, value: Any, data_type: str) -> str | None:
    """§10 — reject invalid type/operator/value combinations. Returns an error
    message, or None when the condition is well-typed."""
    if operator in _NO_VALUE_OPERATORS:
        return None  # presence checks take no value
    if operator in _ORDERED_OPERATORS and data_type not in _ORDERABLE_TYPES:
        return f"Operator {operator} is not supported for type {data_type}."
    if operator == Operator.BETWEEN.value:
        if not isinstance(value, list) or len(value) != 2:
            return "BETWEEN requires a two-element [low, high] value."
        for bound in value:
            if not _scalar_matches_type(bound, data_type):
                return f"BETWEEN bounds must be of type {data_type}."
        return None
    if operator in _LIST_VALUE_OPERATORS:
        if not isinstance(value, list) or not value:
            return f"{operator} requires a non-empty list value."
        for item in value:
            if not _scalar_matches_type(item, data_type):
                return f"Every {operator} item must be of type {data_type}."
        return None
    if operator in _STRING_OPERATORS:
        if not isinstance(value, str):
            return f"{operator} requires a string value."
        if operator == Operator.MATCHES_REGEX.value:
            return validate_regex_pattern(value)
        return None
    if operator in (Operator.CONTAINS.value, Operator.NOT_CONTAINS.value):
        # For arrays/sets the value is an element; for strings a substring.
        if data_type in (AttributeDataType.ARRAY.value, AttributeDataType.SET.value):
            return None
        if data_type == AttributeDataType.STRING.value and isinstance(value, str):
            return None
        return f"{operator} requires an ARRAY/SET attribute or string value."
    # EQUALS / NOT_EQUALS and remaining ordered ops: value must match the type.
    if not _scalar_matches_type(value, data_type):
        return (f"Value {value!r} is not of type {data_type} "
                f"(operator {operator}).")
    return None
