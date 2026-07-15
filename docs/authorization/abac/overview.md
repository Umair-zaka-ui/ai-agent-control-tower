# ABAC engine — overview (Phase 4.3.5)

RBAC answers "does this role hold the permission?"; resource authorization
(4.3.4) answers "may this identity touch this resource?"; **ABAC answers
"should this action be allowed *right now*"** — considering identity, resource,
action, environment, risk, device, data sensitivity and AI-specific context.

## Where it sits

```
Authentication → Identity context → RBAC → Organization hierarchy
  → Resource authorization → ABAC → Final decision + obligations
```

ABAC **never grants what the baseline denied** (§4): a baseline deny is final;
a baseline allow continues into ABAC, which may deny, challenge
(REQUIRE_APPROVAL / REQUIRE_MFA / REQUIRE_JUSTIFICATION), constrain
(MASK_FIELDS / LIMIT_ACTION) or confirm. With no applicable policy the baseline
decision stands (`NOT_APPLICABLE`).

`POST /api/v1/authorization/check` runs this full stack and returns one
normalized decision (`decision`, `allowed`, `reason`, `obligations`).
`POST /api/v1/authorization/abac/evaluate` exposes the ABAC layer directly.

## The pieces

| Piece | Doc |
| --- | --- |
| Policy structure, targets, scopes, effects | [policy-language.md](policy-language.md) |
| Attribute catalog + providers | [attributes.md](attributes.md) |
| Comparison operators + type rules | [operators.md](operators.md) |
| Multiple-policy resolution | [combining-algorithms.md](combining-algorithms.md) |
| Draft → published → archived, versions | [policy-lifecycle.md](policy-lifecycle.md) |
| What-if evaluation | [policy-simulation.md](policy-simulation.md) |
| Threats + guarantees | [security.md](security.md) |

## Decision point vs enforcement point (§26)

The engine is a **policy decision point**: it evaluates and returns. The
**enforcement point** — a route dependency, service command, background worker
or the agent action gateway — acts on the decision and its obligations
(e.g. `CREATE_APPROVAL` routes into the Human Review Workbench; `MASK_FIELDS`
strips the listed fields from the response). The engine never executes
business operations.

## Explainability (§16)

Every decision carries: the policies considered, the policies matched (with
per-condition results), the missing attributes, the winning effect and a
human-readable reason. Values of RESTRICTED-sensitivity attributes are redacted
from user-facing output. Every evaluation is persisted (`abac_evaluations`)
and browsable in the Evaluations viewer; counters and latency are exposed at
`GET /api/v1/authorization/abac/metrics` (§43).

## Administration

Settings → Security → **Context policies (ABAC)**: Policies (visual builder +
lifecycle), Simulator, Attribute catalog, Evaluations viewer, Exceptions.
Gated by the §37 permission set — authoring (`authorization.abac.create/update`)
and publishing (`authorization.abac.publish`) are separable for segregation of
duties.
