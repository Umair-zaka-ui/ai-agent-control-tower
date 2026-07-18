# Compliance Reporting

`/governance/compliance` — Phase 4.3.8 §15, §16. Requires
`governance.compliance.view`.

## Frameworks

`SOC2`, `ISO27001`, `HIPAA`, `GDPR`, `NIST`, `CIS`, `INTERNAL`. Each maps to
platform evidence, not an attempt to automate certification of the framework
itself (§15) — `GET /compliance/frameworks` returns the control → evidence
mapping (`FRAMEWORK_CONTROLS` in `app/governance/services.py`).

| Framework | Control | Platform evidence |
|---|---|---|
| SOC 2 | Logical Access | Certification campaigns |
| ISO 27001 | Access Control | RBAC + access reviews |
| HIPAA | Workforce Access | Role assignments + audit trail |
| GDPR | Least Privilege | Access reviews + SoD findings |
| NIST | Account Management (AC-2) | Identity lifecycle + orphaned-account detection |
| CIS | Access Control Management | SoD/toxic-permission rules + findings |
| Internal | Organizational Policy | Governance findings + remediation log |

## Report generation

`POST /compliance/reports` snapshots current counts into an immutable
`compliance_reports` row (§24 — compliance reports are read-only once
generated): completed/active certification campaigns, open SoD/toxic/
orphaned finding counts, remediated-finding count, completed privileged
reviews, and the current governance risk-band distribution.

## Export

`GET /compliance/reports/{id}?format=json|csv` — JSON is the default; `csv`
flattens the evidence payload into `metric,value` rows. PDF/Excel are not
generated server-side (no new heavy dependency was justified for this) —
the SPA's JSON/CSV export follows the same client-side-conversion pattern
already used by the audit and certification exports elsewhere in this app
(browser print-to-PDF, paste-to-Excel).

## Audit events

`COMPLIANCE_REPORT_GENERATED`.

## API

```
GET  /api/v1/governance/compliance/frameworks
GET  /api/v1/governance/compliance/reports[?framework=]
POST /api/v1/governance/compliance/reports
GET  /api/v1/governance/compliance/reports/{id}[?format=csv]
```
