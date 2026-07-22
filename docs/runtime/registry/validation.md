# Validation engine (§25-§28)

`AgentValidationService.run` (`app/runtime/registry/validation.py`) runs
every rule in one pass — each appends a `ValidationFinding` (code, field,
message, severity) rather than raising immediately, so one run reports
everything wrong at once instead of failing at the first problem — and
persists an `agent_validation_runs` row with a structured `summary`/
`errors`/`warnings`/`checks` report (§26).

## Severity → outcome (§27)

`INFO`/`WARNING` findings never fail a run; `ERROR`/`BLOCKING` findings do
(`status = "FAILED"` if any exist, else `"PASSED"`). `submit-for-approval`
requires the latest run to be `"PASSED"` — a `WARNING`-only run can still
proceed to approval, matching §27's "WARNING: activation may proceed
depending on policy."

## Rule groups (§28)

- **Metadata** — name/description/business_purpose required, `agent_type`
  recognized (`WARNING` if not).
- **Organization/hierarchy** — `project_id`/`business_unit_id`/
  `department_id`/`team_id` must exist and be cross-tenant-consistent
  (project's team must match `team_id` if both given; department's business
  unit must match `business_unit_id` if both given). `Project` has no
  `organization_id` column of its own — membership is checked transitively
  through `team → department → organization_id`.
- **Ownership** — business owner required (`BLOCKING`); technical owner
  required for HIGH/MISSION_CRITICAL criticality (`ERROR`); compliance
  owner required for MISSION_CRITICAL or HIGH/CRITICAL risk (`WARNING`);
  every owner must belong to the same organization (`BLOCKING` if not).
- **Identity** — required (`WARNING` — see
  [identity-association.md](identity-association.md) for why this isn't a
  hard block here); if present, must be eligible (active, unexpired,
  belongs to this agent).
- **Definition** — must exist (`BLOCKING`); entrypoint format validated per
  type (see [json-schema.md](json-schema.md)); framework recognized
  (`WARNING` if not); every schema passes the DoS guards.
- **Risk** — `data_classification` must be a recognized value.

## Reusing execution-time schema validation

The DoS-guard wrapper (`check_schema_dos_guards`) is new; the actual
schema-vs-payload check (`validate_sample_payload`) is the same
`jsonschema.validate` call Phase 5.0's execution-time `_validate_schema`
(`app/runtime/services.py`) already used — both now guard against
maliciously large/deep schemas the same way, since the sample-payload
tester and the execution path share the identical contract.
