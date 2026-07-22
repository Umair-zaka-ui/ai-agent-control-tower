# Machine identity (§11)

`AgentIdentity` (`app/identity/models/agent_identity.py`, Phase 4.2) already
modeled an agent's identity/credential posture — `client_id`,
`credential_type`, `status`, `expires_at` — but Phase 5.0 never enforced any
of it: no uniqueness on `agent_id`, and nothing anywhere read `status` or
`expires_at` before trusting an identity. This phase closes both gaps.

## The 1:1 constraint

`agent_identities.agent_id` now has a `UniqueConstraint` — one machine
identity per agent, DB-enforced. This has a real consequence for what
"associate an existing identity" and "replace" can mean:

- **Associate** (`POST /agents/{id}/identity/associate`) — points
  `agents.identity_id` at an `AgentIdentity` row that already has
  `agent_id == this agent` (e.g. one created earlier via the identity
  module). It is **not** pulling from an unassigned pool — under the 1:1
  constraint, no such pool can exist.
- **Create and associate** (`POST /agents/{id}/identity/create-and-associate`)
  — creates a new `AgentIdentity` scoped to this agent and points at it.
  Rejects with `AGENT_IDENTITY_ALREADY_ASSIGNED` (409) if the agent already
  has one, rather than letting the call hit the unique-constraint
  `IntegrityError` directly.
- **Replace** (`POST /agents/{id}/identity/replace`) — rotates the
  **existing** identity row's `client_id`/`credential_type`/`expires_at` in
  place (same `id`), rather than pointing at a second pre-existing row —
  there can never be one for the same agent. `AgentIdentityAssociationService.replace`
  in `app/runtime/registry/identity.py`.

## Eligibility checks (§11.1)

Enforced in `AgentIdentityAssociationService._check_eligible`: the identity
must belong to this agent, be `status == "ACTIVE"`, and not be expired
(`expires_at` in the past). All three are checked on every associate/
replace call, and again (as a `WARNING`, not a hard block) by the
validation engine — see [validation.md](validation.md).

## Why activation is the real gate, not validation

`AgentLifecycleService.activate` hard-blocks (`AGENT_IDENTITY_REQUIRED`,
422) if `agent.identity_id` is `None` — this is the actual SRS §84
Definition-of-Done requirement ("every active agent must have... a machine
identity"). The validation engine's own identity check is deliberately a
`WARNING` rather than a validation failure, because the registration
wizard's own step ordering (identity is step 4, before contracts/risk are
even filled in) means an otherwise-complete agent shouldn't fail validation
just because identity association hasn't happened yet.
