# ABAC operators (Phase 4.3.5 §9, §10)

Logical nodes: `ALL`, `ANY`, `NOT` (tree structure). Comparison operators map
to small, safe functions in the `OperatorRegistry` — dynamic code execution is
prohibited (§40.2), and an unregistered operator never matches (§40.3).

| Operator | Types | Notes |
| --- | --- | --- |
| `EQUALS` / `NOT_EQUALS` | all | numbers and ISO datetimes are coerced before comparing |
| `IN` / `NOT_IN` | scalars | value must be a non-empty typed list |
| `CONTAINS` / `NOT_CONTAINS` | ARRAY/SET, STRING | element of a list / substring |
| `GREATER_THAN` (`_OR_EQUAL`) | INTEGER, DECIMAL, DATETIME, DATE, TIME, STRING | ordered comparison |
| `LESS_THAN` (`_OR_EQUAL`) | same | |
| `BETWEEN` | ordered types | value is `[low, high]`, inclusive |
| `STARTS_WITH` / `ENDS_WITH` | STRING | |
| `MATCHES_REGEX` | STRING | guarded — see below |
| `EXISTS` / `NOT_EXISTS` | all | tests attribute presence; takes no value |

## Type validation (§10)

`validate_condition_value` runs at policy validation/publish and rejects
invalid combinations — `risk_score > "high"` fails with
`ABAC_ATTRIBUTE_TYPE_MISMATCH` because an INTEGER attribute is compared to a
string. Ordered operators require orderable types; `IN` requires a typed list;
`BETWEEN` requires a two-element typed list.

## Regex safety (§40, §42)

`MATCHES_REGEX` patterns must be ≤256 chars, compile, and contain no nested
quantifier shape (`(a+)+`, `(\d*)*` …) — rejected at validation with a clear
message. As a second layer, runtime refuses to execute any pattern that fails
the same check and caps input at 4096 chars, so a catastrophic pattern can
never stall the engine.
