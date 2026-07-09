# Identity Protection Rules (Phase 4 Part 4.2.2.3.4 §16, §27)

> Beyond the built-in risk thresholds, an organization can author its own
> `conditions → decision` rules. The highest-priority enabled rule that matches an
> attempt wins, and can only make the decision stricter (or explicitly allow).

## The shape of a rule

```json
{
  "name": "Challenge new devices from abroad",
  "priority": 200,
  "enabled": true,
  "decision": "CHALLENGE",
  "conditions": [
    { "field": "new_device", "op": "is_true" },
    { "field": "new_country", "op": "is_true" }
  ]
}
```

A rule **matches** when *all* its conditions match. Rules are evaluated highest
`priority` first; the first match's `decision` is applied.

## Conditions (§16)

| Part | Values |
| ---- | ------ |
| `field` | `risk_score`, `risk_level`, `failed_attempts`, or any anomaly flag (`new_device`, `new_country`, `impossible_travel`, `blocked_ip`, `suspicious_user_agent`, …) |
| `op` | `eq`, `gt`, `gte`, `lt`, `lte`, `in`, `is_true` |
| `value` | the comparison value (omitted for `is_true`) |

## Decisions (§7)

`ALLOW` · `DENY` · `CHALLENGE` · `REQUIRE_MFA` · `LOCK_ACCOUNT` · `BLOCK_IP` ·
`REQUIRE_SECURITY_REVIEW`. Every rule is validated on save — an unknown decision or
operator is rejected with a 422.

## Evaluation order (§14, §16)

```
risk score → baseline decision (thresholds)
           → protection rules override (highest-priority match)
           → CAPTCHA check
           → final decision
```

A triggered rule records a `PROTECTION_RULE_TRIGGERED` event with the rule id, so you can
see which rule fired on which attempt.

## Managing rules (§27)

Settings → Security → Protection rules. Create with a name, decision, priority and a
JSON conditions editor (a visual builder is a documented future enhancement); toggle
`enabled`; delete. Create / update / delete are audited
(`PROTECTION_RULE_CREATED/UPDATED/DELETED`) and require the `security.protection`
permission. Rules are org-scoped.

## Related

- [Risk-based authentication](./risk-based-authentication.md)
- [Account protection overview](./account-protection.md)
