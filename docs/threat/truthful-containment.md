# Truthful containment (Phase 5.6 / M5.6)

**The defining honesty requirement of this phase.** A containment action is
offered and attempted only where ACT genuinely has enforcement authority.
Over-claiming containment — telling an operator an agent was contained when
it was not — is the failure this phase most exists to avoid.

## The one gate

`ContainmentOrchestrator.truthful_capability(agent)` is the single place
capability is decided:

```python
def truthful_capability(self, agent: Agent) -> tuple[bool, str | None]:
    if agent.control_state == "GOVERNED":
        return True, None
    return False, (
        f"ACT has no enforcement authority over this agent "
        f"(control_state={agent.control_state!r}, requires 'GOVERNED'). "
        "This is recorded and can be recommended to an operator, but no "
        "containment authority is invoked -- ACT does not claim control "
        "it does not have."
    )
```

Nothing else in `app/threat/containment.py` may call an authority without
going through this. `GOVERNED` means ACT is the system actually executing
and enforcing this agent (Phase 5.1's control-state lifecycle:
`DISCOVERED → CLAIMED → REGISTERED → GOVERNED`). Anything short of
`GOVERNED` — an agent ACT has only *observed* through discovery (5.2) — gets
a truthful refusal, never an attempted action.

## What a refusal looks like

`POST /threat/agents/{id}/containment` against a `DISCOVERED` agent returns
(HTTP 201 — a refusal is a complete, honest outcome, not an error):

```json
{
  "status": "REFUSED",
  "authority": "KILL_SWITCH",
  "refusal_reason": "ACT has no enforcement authority over this agent (control_state='DISCOVERED', requires 'GOVERNED'). ...",
  "authority_ref": null,
  "result": {}
}
```

`authority` still names which authority *would* have been used — the record
is complete even though nothing was invoked. `authority_ref` and `result`
are both empty: nothing happened, and the record does not pretend otherwise.

## What a real containment looks like

The same request against a `GOVERNED` agent, confirmed:

```json
{
  "status": "EXECUTED",
  "authority": "KILL_SWITCH",
  "authority_ref": {"table": "agents", "id": "…"},
  "result": {"scope": "AGENT", "target_id": "…", "executions_cancelled": 1}
}
```

`agents.lifecycle_status` is genuinely `SUSPENDED` and the agent's running
executions are genuinely `CANCELLED` — verified directly against the row in
`test_ac05_governed_agent_containment_routes_to_the_real_authority` and the
§14 end-to-end proof, not asserted from the response alone.

## Why `control_state`, not `origin_category`

A NATIVE agent that has not yet reached `GOVERNED` (mid-registration) has no
running executions to contain in practice, so the gate rarely binds for
native agents — but it is still the correct, single signal: `GOVERNED` is
literally "ACT enforces this," which is exactly the question truthful
containment has to answer. Using `origin_category` instead would conflate
*where an agent came from* with *whether ACT can act on it*, and an
externally-discovered agent an operator has since claimed and fully governed
must get full containment — the gate has to track control, not origin.

## The seam this phase leaves for 5.7

`control_state == GOVERNED` is a coarse binary. Phase 5.7 (the external
governance gateway) introduces a richer enforcement-mode vocabulary
(`GATEWAY_ENFORCED` / `ADVISORY` / …) that will refine *what kind* of
containment is truthfully available for a gateway-mediated external agent —
more than "none," less than full native containment. 5.6 does not
anticipate that vocabulary; it uses the one signal that exists today and
names the seam explicitly (ADR-0020) rather than guessing at 5.7's shape.
