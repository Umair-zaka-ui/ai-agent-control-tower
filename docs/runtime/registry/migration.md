# Legacy migration classification (§70-§73)

There is no external pre-registry system in this codebase to migrate
*from* — `agents` already **is** the one registry, and always has been
(Phase 5.0's module docstring says as much). So "legacy agent" here means
exactly one thing: a row created under Phase 5.0's simpler registration
flow (name + criticality + a 3-field definition, no mandatory ownership or
identity) before this phase shipped its richer requirements.

`AgentMigrationService.classify_all` (`app/runtime/registry/migration.py`)
classifies every not-yet-classified agent in the caller's organization
against the SRS §71 categories:

- `MISSING_ORGANIZATION`, `MISSING_OWNER`, `MISSING_IDENTITY`,
  `MISSING_DEFINITION`, `INVALID` (identity present but missing/inactive),
  `REQUIRES_MANUAL_REVIEW` (description/business_purpose absent — needed
  for §19.2 registration but not auto-derivable), or `MIGRATION_READY`.
- `DUPLICATE` is not produced by this classifier — duplicate status comes
  from the dedicated [duplicate-detection.md](duplicate-detection.md)
  engine instead of being folded into migration classification.

## Idempotent, not automatic

Calling `POST /agents/migration/classify` again only classifies agents that
don't already have an `agent_migration_records` row — it never
re-classifies or overwrites a prior classification. No agent's
`lifecycle_status` is ever changed by this service — §70's own diagram ends
at "Manual Review," not at an automatic state change; an existing `ACTIVE`
agent stays `ACTIVE` regardless of what it's missing by this phase's new
requirements.

## What it does backfill

Opportunistically, and independent of classification outcome:
`business_unit_id`/`department_id`/`team_id` are derived from `project_id`
(`_derive_org_hierarchy`, the same helper `POST /agents` uses) when the
agent has a project but none of those three columns set yet. This is the
one place migration *does* write to the agent row — everything else is
read-only classification.

## Frontend

`/runtime/migration` (`MigrationPage.tsx`) surfaces both endpoints: a button
to run classification and a table of `AgentMigrationRecord` rows (status,
warnings, batch, timestamp), gated behind the same `runtime.agent.import`
permission as the Import/Export pages.
