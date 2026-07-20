# Capabilities & tools

`/runtime/capabilities`, `/runtime/tools`, and the Capabilities/Tools
sections of the Agent Detail page.

## Capabilities (§18, §19)

A capability (`capabilities` table, global catalog — not org-scoped, since
"what an agent can be designed to do" is a platform taxonomy, e.g.
`SEND_EMAIL`, `EXECUTE_CODE`, `ACCESS_PHI`) **declares potential behavior;
it does not by itself authorize anything**. Assigning `ACCESS_PHI` to an
agent doesn't let it read PHI — it's a governance record that the agent is
*designed* to, which the Runtime Policy layer, ABAC and the capability's own
`requires_approval` flag can act on separately.

`POST /agents/{id}/capabilities {capability_id}` creates an
`agent_capabilities` row: `status=APPROVED` immediately if the capability's
`requires_approval` is false, otherwise `REQUESTED` pending a
`POST /agents/{id}/capabilities/{assignment_id}/decide?approve=true|false`
call (`runtime.capability.manage`).

## Tools (§20, §23, §43)

A tool (`tools` table, optionally org-scoped — `organization_id=null` means
a platform-wide tool) is a callable the agent can invoke at runtime:
`tool_type` (`FUNCTION`/`INTERNAL_API`/`EXTERNAL_API`/`DATABASE`/
`CONNECTOR`/…), `risk_level`, `side_effect_level`, `timeout_seconds`.
Assignment (`agent_tools`) works the same shape as capabilities —
`allowed_actions` (e.g. `["EXECUTE"]`) and free-form `constraints` JSONB
(§23), all enforced by the gateway:

- **`read_only`** — blocks `WRITE`/`DELETE`/`EXPORT`/`ADMINISTRATIVE`
  actions (§22's action vocabulary); `EXECUTE`/`READ` still pass.
- **`maximum_calls_per_execution`** — counts this execution's own
  already-`ALLOWED` calls to this tool; the call that would exceed the
  limit is denied.
- **`allowed_domains`** — checked against the tool's `endpoint_reference`
  host. This is enforced even though most tool types never actually make
  the outbound call in this build (see below) — it's still a real,
  checkable authorization decision independent of whether the call would
  go anywhere.

A constraint violation is recorded as a `DENIED` `tool_calls` row with
`error_code=TOOL_CONSTRAINT_VIOLATION` (distinct from
`TOOL_ACTION_NOT_ALLOWED`, which means "not connected in this
environment" — see below) and is non-retryable: retrying the same
execution won't change the constraint.

## What actually executes (§43, §44)

The Tool Gateway (`ToolGatewayService.invoke`) is the only way a tool call
happens — an agent never calls a tool directly. It:

1. Looks up the tool by name (org-scoped or platform-wide), rejects if
   disabled (`TOOL_NOT_FOUND`).
2. Looks up an `APPROVED` `agent_tools` assignment for this agent+tool
   (`TOOL_NOT_ASSIGNED` otherwise — the agent literally cannot call a tool
   it hasn't been granted).
3. Checks the requested `action` is in `allowed_actions`
   (`TOOL_ACTION_NOT_ALLOWED` otherwise).
4. Checks every constraint above (`TOOL_CONSTRAINT_VIOLATION` on the first
   one that fails).
5. **Only then**, if `tool_type == FUNCTION` and `action` is `EXECUTE` or
   `READ`, runs the built-in echo behavior (returns the input unchanged,
   records a `tool_calls` row, `status=ALLOWED`). Every other tool
   type/action is fully authorized by steps 1-4 but fails closed at step 5
   — `TOOL_ACTION_NOT_ALLOWED`, "tool type not connected in this
   environment." This is deliberate: this build does not make outbound
   HTTP calls or execute arbitrary code on an agent's behalf (no SSRF
   surface, no code-execution surface), while still fully exercising the
   authorization *and* constraint pipeline real tool types would go
   through.

See [gateways.md](gateways.md) for how this composes with the Model Gateway
inside one worker attempt.
