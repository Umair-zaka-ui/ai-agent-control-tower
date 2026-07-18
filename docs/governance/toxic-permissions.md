# Toxic Permission Detection

`/governance/toxic-permissions` — Phase 4.3.8 §10. Rules require
`governance.toxic.manage`; reading rules/findings requires
`governance.sod.view` (the shared read gate for both detection surfaces).

## Same engine as SoD

Toxic-permission rules are `sod_rules` rows with `rule_type=TOXIC_PERMISSION`
— identical shape and detection logic to
[SoD rules](sod-analysis.md): two permission/role-code sets that must not
co-occur on one identity. The distinction is intent, not mechanism —
excessive privilege (e.g. `ROLE_PLATFORM_ADMIN` + `ROLE_SECURITY_ADMIN`,
"Export PHI" + "Delete Audit Logs") rather than a business-process conflict.

Findings land as `governance_findings` rows with
`finding_type=TOXIC_PERMISSION`.

## Detection

Continuous, exactly as SoD: `POST /toxic-findings/scan` runs an org-wide scan
against every `ACTIVE` toxic-permission rule, and every role assignment
triggers a best-effort scan of the assigned identity (§10 — "detection runs
continuously and during role assignment").

## API

```
GET    /api/v1/governance/toxic-rules[?status=]
POST   /api/v1/governance/toxic-rules
POST   /api/v1/governance/toxic-rules/{id}/activate
POST   /api/v1/governance/toxic-rules/{id}/disable
GET    /api/v1/governance/toxic-findings[?status=]
POST   /api/v1/governance/toxic-findings/scan
```

## Audit events

`TOXIC_PERMISSION_FOUND` (plus `SOD_RULE_CREATED`/`SOD_RULE_ACTIVATED` on the
shared rule table).
