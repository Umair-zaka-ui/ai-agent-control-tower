# Enterprise Agent Registry — Overview

Phase 5.1 · extends `/api/v1/runtime/agents` · frontend at `/runtime/agents`.

Phase 5.0 built the execution layer (register → version → deploy → execute)
on top of a deliberately minimal registry: a 3-field creation form, an
8-state lifecycle with no real validation/approval gate, and no accountable
ownership beyond a bare `owner_type`/`owner_id`. Phase 5.1 is the enterprise
registry those executions should have been gated by all along: accountable
ownership with history, a mandatory machine identity, org-hierarchy scoping,
a real validation-report engine, duplicate detection, JSON/YAML/CSV
import/export, and optimistic concurrency — all as the gate every agent must
pass through before it can version, deploy or execute.

> No AI agent may be deployed or executed through the platform unless it is
> first registered and validated through this module.

## What's here

| Doc | Covers |
|---|---|
| [domain-model.md](domain-model.md) | The `agents`/`agent_definitions` extensions and the 7 new registry tables |
| [registration.md](registration.md) | The 10-step registration wizard, draft creation, the `register` lifecycle action |
| [agent-definitions.md](agent-definitions.md) | Framework/entrypoint/requirement declarations |
| [identity-association.md](identity-association.md) | Mandatory machine identity, the 1:1 constraint, associate/create/replace |
| [ownership.md](ownership.md) | Accountable ownership, the transfer flow, immutable history |
| [lifecycle.md](lifecycle.md) | The full 13-state transition matrix, superseding Phase 5.0's 8-state one |
| [validation.md](validation.md) | The validation-report engine: metadata/org/ownership/identity/definition/risk rules |
| [json-schema.md](json-schema.md) | DoS guards, sample-payload testing, entrypoint format validation |
| [duplicate-detection.md](duplicate-detection.md) | Exact + similarity duplicate detection, review decisions |
| [import-export.md](import-export.md) | JSON/YAML/CSV bulk import/export, job tracking, secret redaction |
| [migration.md](migration.md) | Legacy-agent classification (Phase 5.0 rows predating this phase) |
| [security.md](security.md) | Tenant isolation, credential rejection, CSV-injection guards, concurrency |
| [api.md](api.md) | The full REST surface added in this phase |

## What's deliberately not here

A visual drag-and-drop schema builder (the Contracts step uses a raw-JSON
textarea + live validation + sample-payload testing instead — the same
pattern already established by the policy module's condition builder, since
no code-editor library is installed in this frontend). A background
job-processing worker for import/export (both run synchronously inline,
the same "eager" trick the Phase 5.0 execution queue already uses — see
[import-export.md](import-export.md)). Cascading
organization/project/team pickers in the registration wizard (IDs are
entered directly; a picker UI is a frontend-only enhancement that doesn't
change any contract described here).

## Quick reference

- Creating an agent (`POST /agents`) and the `register` lifecycle action
  (`POST /agents/{id}/register`) are two different operations — the SRS
  itself keeps them separate. See [registration.md](registration.md).
- The org hierarchy (`Organization → BusinessUnit → Department → Team →
  Project`) already existed in full before this phase (Phase 4.3.3) — this
  phase denormalizes `business_unit_id`/`department_id`/`team_id` onto
  `agents` for fast filtering, deriving them from `project_id` when not
  given explicitly. See [domain-model.md](domain-model.md).
- `risk_level` (LOW/MEDIUM/HIGH/CRITICAL) already existed on `agents` from
  Phase 3 — this phase's declared risk classification reuses it rather than
  forking a second column ("MODERATE" in the SRS maps to "MEDIUM").
