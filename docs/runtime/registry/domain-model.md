# Domain model

All additive — nothing here forks a parallel registry (see the module
docstring in `backend/app/models/agent_registry.py`).

## `agents` — new columns (migration `0024_agent_registry`)

`business_unit_id`, `department_id`, `team_id` (nullable FKs, denormalized
for fast filtering — derived from `project_id`'s team→department→business
unit chain at registration time when not given explicitly, see
`_derive_org_hierarchy` in `app/runtime/services.py`), `identity_id`
(nullable FK → `agent_identities.id`), `display_name`, `business_purpose`,
`autonomy_level`, `technical_owner_id`/`compliance_owner_id`,
`support_contact`, `documentation_url`/`repository_url`, `tags` (JSONB),
`metadata` (JSONB, mapped as `Agent.extra_metadata` — `metadata` is reserved
by SQLAlchemy's declarative base), `registration_source`,
`external_reference`, `created_by`/`updated_by`, `validated_at`/
`approved_at`/`activated_at`/`suspended_at`/`retired_at` (`archived_at`
already existed), and `row_version` (optimistic concurrency, §53 — see
[security.md](security.md)).

`risk_level` is **not** a new column — it already existed (Phase 3,
LOW/MEDIUM/HIGH/CRITICAL) and this phase's declared risk classification
reuses it.

Two new constraints: `UniqueConstraint(organization_id, slug)` and
`UniqueConstraint(organization_id, external_reference)` — both allow
multiple NULLs (Postgres doesn't compare NULLs for uniqueness), so existing
rows with no slug/external_reference are unaffected.

## `agent_definitions` — new columns

`framework_version`, `runtime_language`, `capability_declarations`,
`tool_declarations` (JSONB lists — declarations of intent, not grants),
`model_requirements`/`memory_requirements`/`data_requirements`/
`network_requirements`/`secret_requirements`/`runtime_requirements` (JSONB,
all default `{}`), `created_by`/`updated_by`, `updated_at`.

## `agent_identities` — new constraint

`UniqueConstraint(agent_id)` — one machine identity per agent, DB-enforced.
Phase 5.0 left this table's `agent_id` unconstrained and its `status`/
`expires_at` unchecked anywhere; this phase both constrains and enforces
them (see [identity-association.md](identity-association.md)).

## New tables

| Table | Purpose | Model |
|---|---|---|
| `agent_ownership_history` | Immutable ownership-change ledger | `AgentOwnershipHistory` |
| `agent_lifecycle_events` | Structured lifecycle-transition ledger (richer than the generic `runtime_events` payload blob — real `previous_status`/`new_status`/`request_id`/`correlation_id` columns for the Lifecycle tab and audit queries) | `AgentLifecycleEvent` |
| `agent_validation_runs` | One row per validation-engine run | `AgentValidationRun` |
| `agent_duplicate_matches` | Exact/similarity duplicate-detection results + reviewer decisions | `AgentDuplicateMatch` |
| `agent_import_jobs` / `agent_import_items` | Import job + per-record outcome | `AgentImportJob` / `AgentImportItem` |
| `agent_export_jobs` | Export job; `payload` holds the rendered content inline (no object-storage service in this environment for `storage_reference` to point at) | `AgentExportJob` |
| `agent_migration_records` | Legacy-agent classification audit | `AgentMigrationRecord` |

Every lifecycle/registry event is dual-written into the existing
`authorization_audit` trail (`_record_event` in `app/runtime/services.py`)
as well as its dedicated table above — the same pattern Phase 5.0
established, not a new one.
