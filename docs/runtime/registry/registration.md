# Registration

`POST /api/v1/runtime/agents` creates the initial `DRAFT` row
(`AgentRegistryService.register` in `app/runtime/services.py`) — this is a
**different** operation from the `register` **lifecycle action**
(`POST /agents/{id}/register`, `AgentLifecycleService.register` in
`app/runtime/registry/services.py`), which moves an already-created draft
`DRAFT → REGISTERED`. The SRS itself keeps these as two operations; so does
this implementation.

## What `POST /agents` does

1. Resolves `project_id` (if given) and derives `business_unit_id`/
   `department_id`/`team_id` from its team→department→business-unit chain
   when those aren't given explicitly (`_derive_org_hierarchy`).
2. Rejects `documentation_url`/`repository_url` values with embedded
   credentials (`check_url_for_embedded_credentials`, §69).
3. Generates a slug from `name` if not given (`_generate_slug` — lowercase,
   letters/numbers/hyphens, no consecutive hyphens, begins with a letter or
   number, reserved names get a `-agent` suffix) and de-duplicates it within
   the organization (`_unique_slug` — appends `-2`, `-3`, …).
4. Rejects a duplicate `external_reference` within the organization
   (`AGENT_EXTERNAL_REFERENCE_CONFLICT`, 409) — pre-checked before the
   insert, backed by the DB unique constraint either way.
5. Creates the `Agent` row (`lifecycle_status="DRAFT"`) and its
   `AgentDefinition` in the same transaction.

Every field beyond `name` and the definition's `entrypoint` is optional at
this stage — a `DRAFT` agent is allowed to be incomplete (§19.1).

## The registration wizard (frontend)

`frontend/src/modules/runtime/registry/RegistrationWizardPage.tsx` — 9
rendered steps (Basic Info, Org Placement, Ownership, Machine Identity,
Technical Definition, Contracts, Risk & Classification, Capabilities &
Tools, Review); "Submit" (SRS step 10) is the Review step's action rather
than its own empty screen, matching the existing `PolicyBuilder.tsx`
pattern in this codebase (step index + flat state + per-step validation +
a shared `Stepper`).

The Machine Identity step is deliberately informational, not a form field:
an identity can only be created once the agent record exists
(`AgentIdentityAssociationService.create_and_associate` requires an
`agent.id`), so the wizard tells the user to visit the agent's **Identity**
tab after registering rather than pretending to collect it up front.

### Draft autosave

The wizard has no server-side draft record until the final submit, so every
field change is persisted to `localStorage`
(`runtime.agent.registration.draft.v1`) as the user types. On mount, a
prior draft is restored automatically (with a dismissible "Restored your
unsaved draft" banner and a Discard action); the draft is cleared once
`POST /agents` succeeds. This is purely a client-side convenience against a
closed tab or crash — it has no bearing on the server-side optimistic
concurrency (`row_version`) used once the agent record exists (see
[api.md](api.md)).

## Registering (the lifecycle action)

`AgentLifecycleService.register` requires `name`, `description`,
`business_purpose`, and an `owner_id` to all be set — raises
`AGENT_DEFINITION_REQUIRED` (422) otherwise. This is SRS §19.2's "minimum
required information has been submitted" gate, enforced in code rather than
left as a UI convention.

Allowed from `DRAFT`, `VALIDATION_FAILED`, or `REJECTED` (§20) — the latter
two so a corrected or resubmitted agent doesn't need to go all the way back
to `DRAFT` first.
