"""ABAC condition evaluator (Phase 4.3.5 §9, §24).

Recursively evaluates the nested condition tree:

    {"all": [ ... ]}   every child must match
    {"any": [ ... ]}   at least one child must match
    {"not":  ... }     child must not match
    {"attribute": "...", "operator": "...", "value": ...}   leaf

A leaf whose attribute is absent from the context evaluates ``False`` (safe:
a DENY policy that cannot verify its trigger does not fire; a missing-attribute
allow never grants) — except ``EXISTS`` / ``NOT_EXISTS``, which act on
presence itself. Every leaf result lands in the trace for explainability (§16).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.authorization.abac.enums import Operator
from app.authorization.abac.operators import OperatorRegistry

_MISSING = object()


@dataclass
class ConditionTrace:
    """The evaluation record of one condition tree — feeds the explanation."""

    results: list[dict] = field(default_factory=list)
    missing_attributes: list[str] = field(default_factory=list)

    def record(self, attribute: str, operator: str, expected: Any,
               result: bool, missing: bool) -> None:
        self.results.append({
            "attribute": attribute, "operator": operator, "expected": expected,
            "result": result, "missing": missing,
        })
        if missing and attribute not in self.missing_attributes:
            self.missing_attributes.append(attribute)


class ConditionEvaluator:
    """§24 — pure, recursive evaluation over a flat attribute context
    (``{"resource.contains_phi": True, ...}``)."""

    MAX_DEPTH = 32  # deeply nested trees are rejected at validation; belt & braces here

    @classmethod
    def evaluate(cls, node: dict | None, context: dict[str, Any],
                 trace: ConditionTrace | None = None, _depth: int = 0) -> tuple[bool, ConditionTrace]:
        trace = trace if trace is not None else ConditionTrace()
        if node is None or node == {}:
            return True, trace  # a policy without conditions matches its target
        if _depth > cls.MAX_DEPTH:
            return False, trace

        if "all" in node:
            ok = all(cls.evaluate(child, context, trace, _depth + 1)[0] for child in node["all"])
            return ok, trace
        if "any" in node:
            children = node["any"]
            # Evaluate every child so the trace is complete (no short-circuit).
            results = [cls.evaluate(child, context, trace, _depth + 1)[0] for child in children]
            return any(results), trace
        if "not" in node:
            ok, _ = cls.evaluate(node["not"], context, trace, _depth + 1)
            return not ok, trace

        # Leaf condition.
        attribute = node.get("attribute", "")
        operator = node.get("operator", "")
        expected = node.get("value")
        actual = context.get(attribute, _MISSING)
        missing = actual is _MISSING

        if operator == Operator.EXISTS.value:
            result = not missing and context.get(attribute) is not None
        elif operator == Operator.NOT_EXISTS.value:
            result = missing or context.get(attribute) is None
        elif missing:
            result = False
        else:
            result = OperatorRegistry.apply(operator, actual, expected)

        trace.record(attribute, operator, expected, result, missing)
        return result, trace

    @classmethod
    def depth_of(cls, node: dict | None, _depth: int = 0) -> int:
        """Depth of a condition tree (used by validation to cap nesting)."""
        if not isinstance(node, dict) or not node:
            return _depth
        if "all" in node or "any" in node:
            children = node.get("all") or node.get("any") or []
            return max([_depth + 1] + [cls.depth_of(c, _depth + 1) for c in children])
        if "not" in node:
            return cls.depth_of(node["not"], _depth + 1)
        return _depth + 1

    @classmethod
    def leaves_of(cls, node: dict | None) -> list[dict]:
        """Every leaf condition in a tree (used by validation)."""
        if not isinstance(node, dict) or not node:
            return []
        if "all" in node or "any" in node:
            children = node.get("all") or node.get("any") or []
            out: list[dict] = []
            for child in children:
                out.extend(cls.leaves_of(child))
            return out
        if "not" in node:
            return cls.leaves_of(node["not"])
        return [node]
