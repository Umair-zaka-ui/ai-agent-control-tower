# ABAC attributes (Phase 4.3.5 §5, §18–§20)

Only **registered** attributes may appear in policies (§40.4). The registry
(`attribute_definitions`) declares each attribute's category, data type,
sensitivity and supported operators; ~70 system attributes are seeded
idempotently, and `authorization.attribute.manage` holders can register custom
ones (`POST /api/v1/authorization/attributes`).

## Categories (§5)

- **SUBJECT** (`identity.*`) — id, type (HUMAN_USER/AI_AGENT/SERVICE_ACCOUNT/
  EXTERNAL_CLIENT/SYSTEM), status, roles, org/department/team, risk_score
  (latest login), mfa_verified, account_age_days, …
- **RESOURCE** (`resource.*`) — id, type, owner, org + hierarchy path,
  classification (PUBLIC→REGULATED), sensitivity (LOW→CRITICAL),
  contains_pii/phi/financial_data, model_provider/name, tags, …
- **ACTION** (`action.*`) — name, category, read_only, destructive,
  data_export, target_count, estimated_cost, …
- **ENVIRONMENT** (`environment.*`) — timestamp, day_of_week, business_hours
  (Mon–Fri 09–17 UTC), ip_address, network_zone (CORPORATE→BLOCKED),
  device_trust, session_risk, request_risk, production, incident_active, …
- **AI** (`ai.*`) — agent, model, autonomy_level (ASSISTIVE→CRITICAL_AUTONOMOUS),
  confidence/hallucination/toxicity scores, pii/phi_detected, tool_name/risk,
  execution_cost, …

## Providers (§19) and the context builder (§18)

`AttributeContextBuilder` is the only place evaluation contexts are assembled —
controllers never hand-build policy dictionaries. One provider per category:

- `SubjectAttributeProvider` — from the User row, role assignments and the
  latest login risk score.
- `ResourceAttributeProvider` — from the 4.3.4 resource registry plus the
  4.3.3 hierarchy path.
- `ActionAttributeProvider` — derived from the permission code (read_only,
  destructive, data_export heuristics).
- `EnvironmentAttributeProvider` — clock, request IP, request/correlation ids.
- `AIAttributeProvider` — AI attributes originate at the calling gateway and
  arrive as request context.

Request context is merged on top, category by category, using fully-qualified
dotted names — **`identity.*` overrides are dropped** on live evaluation paths
(only the permission-gated simulator may supply them). An attribute nobody
provided is simply absent: conditions referencing it fail safe, it is listed in
the decision's `missing_attributes`, and `abac_missing_attributes_total` is
incremented.

## Sensitivity (§16, §40.7)

`PUBLIC` / `INTERNAL` / `RESTRICTED`. RESTRICTED values (risk scores, IPs,
clearance, PII/PHI flags) are replaced with `[REDACTED]` in user-facing
explanations; full detail stays in `abac_evaluations`, readable only with
`authorization.abac.audit`.
