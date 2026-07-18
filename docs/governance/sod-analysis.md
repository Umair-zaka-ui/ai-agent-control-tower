# Separation of Duties (SoD)

`/governance/sod-rules` (rules) + `/governance/sod-findings` (findings) —
Phase 4.3.8 §9. Rules require `governance.sod.manage` to create/activate/
disable; both pages require `governance.sod.view` to read.

## Model

A rule (`sod_rules` table, `rule_type=SOD`) names two permission sets,
`permissions_a` and `permissions_b`. An identity **violates** the rule when
its effective permissions — the union across every active, non-expired role
assignment, with role-hierarchy inheritance resolved exactly as the
authorization engine resolves it — intersect *both* sets.

See [toxic-permissions.md](toxic-permissions.md): toxic-permission rules use
the same table and engine (`rule_type=TOXIC_PERMISSION`) — SoD is a
business-process conflict (e.g. "approve payment" + "issue payment"), a
toxic-permission rule is raw over-privilege (e.g. two admin roles combined).
One engine, two intents.

## Rule lifecycle

```
DRAFT → ACTIVE → DISABLED
```

`POST /sod-rules/{id}/activate` requires approval (§24): the activating actor
is recorded as `approved_by`/`approved_at`. Only `DRAFT`/`DISABLED` rules can
be edited — disable an `ACTIVE` rule before changing its permission sets.

## Detection

Detection is **continuous**, not just on-demand (§10):

- `POST /sod-findings/scan` — org-wide scan against every `ACTIVE` rule.
- Every `POST /api/v1/role-assignments` also runs a best-effort scan of the
  assigned identity (`app/authorization/routes.py::_scan_sod_best_effort`) —
  wrapped so a scan failure never blocks the assignment it observes.

A scan never duplicates an already-`OPEN` finding for the same
(identity, rule) pair — re-scanning is safe to call repeatedly.

## Findings

A match creates a `governance_findings` row (`finding_type=SOD_VIOLATION`),
severity = the rule's `risk_level`, with `details.matched_a`/`matched_b`
recording which codes tripped it. See
[docs/governance/remediation.md](remediation.md) for resolving one.

## Audit events

`SOD_RULE_CREATED`, `SOD_RULE_ACTIVATED`, `SOD_VIOLATION_FOUND`.

## API

```
GET    /api/v1/governance/sod-rules[?status=]
POST   /api/v1/governance/sod-rules
PUT    /api/v1/governance/sod-rules/{id}
POST   /api/v1/governance/sod-rules/{id}/activate
POST   /api/v1/governance/sod-rules/{id}/disable
GET    /api/v1/governance/sod-findings[?status=]
POST   /api/v1/governance/sod-findings/scan
```
