# ABAC combining algorithms (Phase 4.3.5 §13, §14)

Several policies can match one request. Matched policies are sorted by scope
breadth (platform → resource) then priority, `LOG_ONLY` matches are set aside
as observations, and the algorithm resolves the rest.

| Algorithm | Resolution |
| --- | --- |
| `DENY_OVERRIDES` *(default)* | any DENY wins; else the strongest challenge (approval > MFA > justification); else a constraint (mask/limit); else ALLOW |
| `ALLOW_OVERRIDES` | any ALLOW wins; otherwise falls back to deny-overrides ordering |
| `FIRST_APPLICABLE` | the first matched policy (scope + priority order) decides |
| `HIGHEST_PRIORITY` | the highest-priority matched policy decides (ties resolved deny-overrides) |
| `ALL_MUST_ALLOW` | every matched policy must be ALLOW, else the first non-allow effect wins (DENY if any) |

The engine uses the highest-precedence matched policy's
`combining_algorithm`; with no matches the decision is `NOT_APPLICABLE` and
the baseline stands.

## Worked example (§14)

- Policy A: `ALLOW` dataset export
- Policy B: `DENY` export outside the corporate network
- Policy C: `REQUIRE_APPROVAL` above 10,000 rows

Request: network `PUBLIC`, 20,000 rows → A, B and C all match →
`DENY_OVERRIDES` → **DENY** (deny beats approval beats allow). All three appear
in `explanation.matched_policies`, and the approval obligation is stripped
because a deny renders it moot.

## Exceptions

An approved, unexpired [policy exception](policy-lifecycle.md#exceptions)
removes one policy from the matched set for one subject before combination.
