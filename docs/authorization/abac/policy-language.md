# ABAC policy language (Phase 4.3.5 §6, §9, §11, §12)

A policy is data, never code: a **target** (what requests it applies to), a
**condition tree** (when it fires), an **effect** (what happens) and optional
**obligations** (what the enforcement point must do).

```json
{
  "name": "Restrict PHI export",
  "priority": 100,
  "scope_type": "ORGANIZATION",
  "target": {"actions": ["dataset.export"]},
  "conditions": {
    "all": [
      {"attribute": "resource.contains_phi", "operator": "EQUALS", "value": true},
      {"attribute": "environment.network_zone", "operator": "NOT_IN",
       "value": ["CORPORATE", "TRUSTED_VPN"]}
    ]
  },
  "effect": "DENY"
}
```

## Target (§11)

`resource_types`, `actions` (exact or `prefix.*`), `identity_types`, `roles`,
`classifications` — lists of strings; empty/missing keys match everything.

## Conditions (§9)

Nested tree of `{"all": [...]}` (AND), `{"any": [...]}` (OR), `{"not": ...}`
and leaves `{"attribute", "operator", "value"}`. Max depth 16. A leaf whose
attribute is missing from the context evaluates **false** (a DENY that cannot
verify its trigger does not fire; a missing-attribute allow never grants);
`EXISTS`/`NOT_EXISTS` test presence itself. Only
[registered attributes](attributes.md) and
[registered operators](operators.md) are accepted.

## Effects (§8)

| Effect | Meaning |
| --- | --- |
| `ALLOW` | allow (baseline already passed) |
| `DENY` | block |
| `REQUIRE_APPROVAL` | route into the Human Review Workbench (obligation `CREATE_APPROVAL` with `priority`, `reviewer_role`) |
| `REQUIRE_MFA` | stronger authentication required |
| `REQUIRE_JUSTIFICATION` | the user must supply a reason |
| `MASK_FIELDS` | allow, minus `obligations.fields` |
| `LIMIT_ACTION` | allow within `obligations` limits (e.g. `maximum_export_rows`) |
| `LOG_ONLY` | record an observation; never changes the decision (staged rollout) |

## Scopes (§12)

`PLATFORM` (every tenant; requires platform administration, cannot be
overridden by org policies), `ORGANIZATION`, `BUSINESS_UNIT`, `DEPARTMENT`,
`TEAM`, `PROJECT` (match the resource's hierarchy path or the subject's
placement), `RESOURCE` (one resource). Broader scopes sort first at combination
time.

## Validity

`valid_from` / `valid_until` bound a policy in time; expired policies are
skipped at resolution.
