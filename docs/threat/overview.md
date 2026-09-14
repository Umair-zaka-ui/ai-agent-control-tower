# Runtime Threat Detection & Containment (Phase 5.6 / M5.6)

5.5 made risk *visible* — posture findings, signals only. 5.6 gives the
milestone its **teeth**: deterministic runtime threat detection over the
signals M4 already produces (behavioral findings, governance decisions, tool
calls) plus 5.4/5.5 evidence, and containment that routes **only** to
enforcement authorities the platform already has. See
[ADR-0020](../architecture/adr/0020-truthful-containment-via-existing-authorities.md)
for the full design reasoning.

## Threat vs. posture

A threat is a **runtime event** ("this happened just now"); posture (5.5) is
a **standing state** ("this is how things stand"). The canonical example:

> An agent depending on an unapproved MCP server is **posture**. The agent
> actually *invoking* a tool that unapproved server exposes, right now, is a
> **threat** (`unapproved_mcp_tool_invoked`).

`app/threat/rules.py`'s six rules correlate M4 signals over a lookback window
— see [rules.md](./rules.md).

## Containment: orchestration, not enforcement

`ContainmentOrchestrator` (`app/threat/containment.py`) maps one of **seven**
containment actions to exactly **one** existing enforcement authority. There
is no eighth action, and this module implements no enforcement of its own —
every action is a call into a service Milestone 1–4 already built and
proved:

| Action | Authority | Real call |
| --- | --- | --- |
| `TERMINATE_EXECUTION` | KillSwitchService | scope `EXECUTION` |
| `SUSPEND_AGENT` | KillSwitchService | scope `AGENT` |
| `DENY_TOOL` | ToolRegistryService | `.revoke()` — an `agent_tools` grant |
| `REVOKE_CAPABILITY` | CapabilityService | `.revoke()` — an `agent_capabilities` grant |
| `ISOLATE_CREDENTIAL` | `api_key_service.revoke_key` | an `agent_api_keys` row |
| `DISABLE_INTEGRATION` | ConnectorService | `.disable()` — a `connector_instances` row |
| `REQUIRE_APPROVAL` | GovernancePolicyService | `.create()` — a real, mandatory, agent-scoped `requires_approval` policy the 4.3 engine's own checkpoints read |

Every containment action is **confirmation-gated** (`confirm=true`) — all
seven reach an enforcement authority, so none skips it. Without confirmation,
a request is recorded as `PENDING_CONFIRMATION` and nothing is invoked.

## Truthful containment

Capability is derived from exactly one signal: `agents.control_state`.
`GOVERNED` means ACT actually executes/enforces this agent; anything else
(`DISCOVERED`/`CLAIMED`/`REGISTERED`) means it does not. For a non-`GOVERNED`
agent, every enforcement-requiring action comes back `status='REFUSED'` with
a real `refusal_reason` — `authority_ref` and `result` both stay empty.
**There is no code path that fabricates a success.** See
[truthful-containment.md](./truthful-containment.md).

## Kill-switch dominance

`SUSPEND_AGENT` and `TERMINATE_EXECUTION` are `reversible=False` by
construction: nothing in `app/threat` sets `lifecycle_status` back to
`'ACTIVE'` or `cancel_requested` back to `False` (AST-proven,
`test_ac06_no_reactivation_or_kill_clearing_in_threat_package`, the same
property `app.runtime.governance` proves for itself). Automated detection
(`ThreatEvaluator`) never invokes a containment authority — a new HIGH/
CRITICAL finding only ever creates a `RECOMMENDED` action row. A human kill,
once fired, cannot be undone by anything this package does.

## One enforcement path

`app/threat` calls `KillSwitchService`, `RuntimeGovernanceEngine`'s own
`GovernancePolicyService`, `ToolRegistryService`, `CapabilityService`,
`ConnectorService`, and `api_key_service` — it defines no class shaped like
an enforcer, and no direct `UPDATE` of an enforcement column (`agents.status`,
`agent_executions.status`, `agent_tools.status`, …) appears anywhere in the
package (`test_ac04_*`). The 4.3 governance engine and the kill switch remain
the only two things on this platform that can stop or suspend something.

## The finding lifecycle (reused from 4.7, mirroring 5.5)

`threat_findings` is a dedicated table (the ADR-0019/4.5/4.7 "new table, not
a discriminator" call) that reuses the lifecycle **shape** verbatim —
`app.slo.states` is imported, not re-spelled: `OPEN → ACKNOWLEDGED →
RESOLVED → SUPPRESSED`, one open finding per condition (a partial unique
index), reopen-on-recurrence, suppression that is not resolution.

## Failure semantics

- **Detection fails open** — a rule that raises is caught by
  `ThreatEvaluator`; it produces no finding and never blocks anything
  (`rule_errors` is reported).
- **A mandatory containment that cannot complete fails closed** — the
  authority call raised, so the record is `FAILED` with the real error,
  never silently treated as `EXECUTED`.
- **Truthful failure over fake success** — `REFUSED` (no authority) and
  `FAILED` (authority invoked, it raised) are both honest, complete outcomes,
  never conflated with `EXECUTED`.

## API

| Route | Permission | |
| --- | --- | --- |
| `GET /threat/findings` | `threat.view` | filterable |
| `GET /threat/findings/{id}` | `threat.view` | |
| `POST /threat/findings/{id}/acknowledge` `/resolve` `/suppress` | `threat.manage` | |
| `GET /threat/agents/{id}/findings` | `threat.view` | |
| `POST /threat/agents/{id}/evaluate` | `threat.manage` | one agent |
| `POST /threat/evaluate` | `threat.manage` | whole tenant (mirrors the `threat.evaluate` scheduler handler) |
| `GET /threat/containment` / `/{id}` | `threat.view` | |
| `POST /threat/agents/{id}/containment` | **`containment.execute`** | the distinct, stronger permission |
| `POST /threat/containment/{id}/revert` | **`containment.execute`** | reversible actions only |

Tenant-isolated throughout; a cross-tenant finding/containment read or
attempt is 404. No secret ever appears in a threat finding or a containment
record.
