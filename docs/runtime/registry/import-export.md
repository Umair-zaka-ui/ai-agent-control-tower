# Import / export (§39-§45)

Both run **synchronously inline** within the request — the same "eager"
philosophy the Phase 5.0 execution queue already uses (see that module's
own docstring): this environment has no background worker to hand the job
to, so `agent_import_jobs`/`agent_export_jobs` go straight from `PENDING` to
a terminal status before the API call returns. The job/item tables are
still fully populated and queryable; a real deployment with a task queue
could point a worker at `AgentImportService.run_job`/`AgentExportService.run_job`
later without changing their contract.

## Import

`POST /agents/import` (`AgentImportService.run_job`,
`app/runtime/registry/imports_exports.py`):

- **Formats**: JSON, YAML (`yaml.safe_load` only — never `yaml.load`, the
  classic deserialization-RCE vector), CSV (`csv.DictReader`).
- **Size limits**: 5,000,000 bytes / 5,000 records, checked before parsing.
- **Modes**: `CREATE_ONLY` (skip existing), `UPDATE_DRAFTS` (only touch
  existing `DRAFT` agents), `UPSERT_NON_ACTIVE` (create or update anything
  not `ACTIVE`/`APPROVED`), `VALIDATE_ONLY` (parse and report, persist
  nothing).
- **Every new agent lands as `DRAFT`, never directly `ACTIVE`** (§45) —
  `registration_source="IMPORT"` distinguishes it in the audit trail.
- A duplicate check runs on every newly created row; a confirmed match adds
  a warning to that row's `agent_import_items` entry rather than failing
  the import outright.
- Per-record outcome (`CREATED`/`UPDATED`/`SKIPPED`/`FAILED`) with
  structured errors/warnings, queryable via `GET /agents/import/{jobId}/items`.

## Export

`POST /agents/export` (`AgentExportService.run_job`):

- **Export types**: `FULL_CONFIGURATION` (definition included, secret
  fields excluded), `INVENTORY_SUMMARY` (tabular), `COMPLIANCE_REPORT`
  (adds owner/validation/approval timestamps), `MIGRATION_PACKAGE` (same
  shape as full configuration).
- **Secrets never exported** (§43) — `_redact_definition` builds an
  **allowlist** of safe definition fields (name, framework, entrypoint,
  schemas) rather than a denylist of things to strip, so a new sensitive
  field added to `AgentDefinition` later can't leak by omission.
- **CSV formula-injection neutralized** (§69) — `_csv_safe` prefixes any
  value beginning with `=`, `+`, `-`, or `@` with a literal-text guard
  apostrophe, since Excel/Sheets would otherwise interpret it as a formula
  on reopen.
- The rendered payload is stored inline on the `agent_export_jobs` row
  (`payload` column) and streamed back by
  `GET /agents/export/{jobId}/download` — there's no object-storage service
  in this environment for `storage_reference` to point at instead.
