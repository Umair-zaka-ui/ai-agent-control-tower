# Ownership (§12, §13)

Every agent carries `owner_type`/`owner_id` (the business owner, Phase 5.0),
plus this phase's `technical_owner_id` and `compliance_owner_id`.
`SECURITY_OWNER`/`DATA_OWNER` are valid roles in the ownership-history
ledger (§13) but have no dedicated `agents.*` column yet — only the three
above are transferable via a direct field
(`AgentOwnershipService._DIRECT_OWNER_ROLES`,
`app/runtime/registry/ownership.py`).

## Transfer

`POST /agents/{id}/ownership/transfer` (`AgentOwnershipService.transfer`):

- For `owner_role="BUSINESS_OWNER"`, updates `owner_type`/`owner_id`; for
  `TECHNICAL_OWNER`/`COMPLIANCE_OWNER`, updates the corresponding column.
- If `new_owner_type == "USER"`, the new owner must belong to the same
  organization (`AGENT_OWNER_SCOPE_MISMATCH`, 422 otherwise) — §12.3's "the
  owner must belong to the same organization."
- Always writes an `agent_ownership_history` row recording the previous and
  new owner, the reason, and who made the change — the history is
  append-only; there is no endpoint that edits or deletes a history row.

## Requirements enforced at activation, not at transfer

`AgentLifecycleService.activate` (not the transfer endpoint) enforces:

- **Never ownerless** (§14) — `AgentOwnershipService.check_agent_not_ownerless`
  blocks activation of a `MISSION_CRITICAL` agent with no business owner.
- **Compliance owner required for high-risk agents** (§12.2) — a
  `MISSION_CRITICAL`-criticality or `HIGH`/`CRITICAL`-risk agent needs a
  `compliance_owner_id` before it can activate.
- **Technical owner required for high-criticality agents** — enforced as a
  `WARNING`-severity finding in the validation engine (not a hard
  activation block, since it's advisory per §12.2's "may additionally
  require").

These checks live at `activate()` deliberately, not at `register()` or
`transfer()` — an agent can be drafted, and its ownership can even be
transferred mid-lifecycle, without immediately needing every required role
filled in; only the final step before it starts executing enforces
completeness.
