# Lifecycle (§18-§21)

Supersedes Phase 5.0's collapsed 8-state machine (`DRAFT → VALIDATED →
APPROVED → ACTIVE → SUSPENDED → DEPRECATED → ARCHIVED → RETIRED`, where
`validate`/`approve`/`deprecate` each borrowed a neighboring transition's
audit event) with the full 13-state matrix and one dedicated audit event
per action.

## States

```
DRAFT → REGISTERED → VALIDATING → VALIDATED → PENDING_APPROVAL → APPROVED → ACTIVE
                 ↖ VALIDATION_FAILED ↗              ↘ REJECTED
ACTIVE ⇄ SUSPENDED, ACTIVE/SUSPENDED → DEPRECATED ⇄ ACTIVE
{most non-terminal states} → ARCHIVED → DRAFT (restore, authorized only)
ACTIVE/SUSPENDED/DEPRECATED → RETIRED (terminal)
```

The exact matrix is `_TRANSITIONS` in
`app/runtime/registry/services.py` — the single source of truth every
action checks against; `AgentLifecycleService._transition` raises
`AGENT_TRANSITION_NOT_ALLOWED` (409) for anything not in the table.

## Actions and their audit events

| Action | From → To | Audit event |
|---|---|---|
| `register` | DRAFT/VALIDATION_FAILED/REJECTED → REGISTERED | `RUNTIME_AGENT_REGISTERED` |
| `validate` | REGISTERED/VALIDATION_FAILED → VALIDATING → VALIDATED or VALIDATION_FAILED | `RUNTIME_AGENT_VALIDATION_STARTED` then `_PASSED`/`_FAILED` |
| `submit-for-approval` | VALIDATED → PENDING_APPROVAL | `RUNTIME_AGENT_APPROVAL_REQUESTED` |
| `approve` | PENDING_APPROVAL → APPROVED | `RUNTIME_AGENT_APPROVED` |
| `reject` (reason required) | PENDING_APPROVAL → REJECTED | `RUNTIME_AGENT_REJECTED` |
| `activate` | APPROVED → ACTIVE | `RUNTIME_AGENT_ACTIVATED` |
| `suspend` | ACTIVE → SUSPENDED | `RUNTIME_AGENT_SUSPENDED` |
| `resume` | SUSPENDED → ACTIVE | `RUNTIME_AGENT_RESUMED` — a distinct verb/event from `activate`, even though both land on ACTIVE (§67 lists them separately) |
| `deprecate` | ACTIVE/SUSPENDED → DEPRECATED | `RUNTIME_AGENT_DEPRECATED` |
| `archive` | most states → ARCHIVED | `RUNTIME_AGENT_ARCHIVED` |
| `restore` | ARCHIVED → DRAFT | `RUNTIME_AGENT_RESTORED` — gated by its own `runtime.agent.restore` permission, distinct from every other action's |
| `retire` | ACTIVE/SUSPENDED/DEPRECATED → RETIRED | `RUNTIME_AGENT_RETIRED` — terminal, no outgoing edges |

Every transition writes both a row to `agent_lifecycle_events` (structured:
`previous_status`, `new_status`, `reason`, `requested_by`, `approved_by`,
`request_id`, `correlation_id`) and the generic
`authorization_audit`/`runtime_events` dual-write Phase 5.0 already
established (`_record_event`) — the Lifecycle tab reads the former, the
Audit tab and Operations Center feed read the latter.

## Gating order matters

`activate()` checks the transition is legal *before* checking identity/
ownership completeness — an agent still in `DRAFT` gets
`AGENT_TRANSITION_NOT_ALLOWED` (409), not a confusing
`AGENT_IDENTITY_REQUIRED` about a state it can't reach yet.

## Editable states

`EDITABLE_STATES = {DRAFT, REGISTERED, VALIDATION_FAILED, REJECTED}`
(`app/runtime/registry/services.py`) — `AgentRegistryService.update` raises
`AGENT_NOT_EDITABLE` (409) outside these; matches §7/§19.1/§19.4/§19.7's
description of when an agent's definition remains editable.
