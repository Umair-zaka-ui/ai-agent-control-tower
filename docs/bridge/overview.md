# External Agent Governance Bridge — overview

Phase 5.7 / M5.7. This is where ACT governs agents it did not build and does
not run — **truthfully**.

- [Enforcement modes](enforcement-modes.md) — what ACT can and cannot do to
  each agent, and why the strongest mode is not storable.
- [The governed capability boundary](gateway.md) — the flow, the transaction
  discipline, and what is deliberately not proxied.
- [External identity](external-identity.md) — signed requests, scoped grants,
  and why federation was rejected.
- [ADR-0021](../architecture/adr/0021-truthful-external-enforcement-modes.md) —
  the decision record.

## The two rules

**1. Never claim enforcement ACT does not have.** `OBSERVED` sees.
`ADVISORY` advises. `GATEWAY_ENFORCED` authorizes the capability calls an
external agent routes *through ACT* — and reaches nothing else it does.
`NATIVE_ENFORCED` is the M1–M4 platform, where ACT runs the agent and the 4.3
engine and kill switch apply.

The sentence ACT uses for GATEWAY_ENFORCED is "ACT authorizes this agent's
capability calls that route through ACT's gateway", never "ACT governs this
agent". Every mode ships a `limits` string alongside its `display` string, and
both travel in every API response, so a client cannot render the claim without
the bound.

**2. Do not proxy everything.** ACT is not in the path of an external agent's
model calls or network traffic and does not pretend to be. Putting it there
would be unscalable, lock-in-inducing, and — decisively — impossible to
guarantee truthfully, because an agent can always make a call that bypasses the
proxy. ACT governs the specific, declared capability calls an agent chooses to
send through it.

## How the honesty is made structural

It is not a convention anyone has to remember:

- **`NATIVE_ENFORCED` is not a storable value.** A `CHECK` constraint on
  `agents.external_enforcement_mode` admits only
  `OBSERVED`/`ADVISORY`/`GATEWAY_ENFORCED`. Full enforcement is *derived* from
  `control_state = 'GOVERNED'` — the same signal Phase 5.6's containment gate
  reads — so it has to be true rather than declared, and the two phases cannot
  drift apart.
- **A GATEWAY_ENFORCED agent is not `GOVERNED`.** Marking it so would make
  5.6's `SUSPEND_AGENT` claim success for an agent ACT cannot suspend. It stays
  `REGISTERED`, and 5.6 keeps refusing.
- **`app/bridge/observed.py` imports no enforcement authority at all** — the
  AST proof that OBSERVED and ADVISORY enforce nothing, the same technique 5.6
  used on `app/threat`.
- **A denied call can never carry a dispatch** — a database `CHECK`, not a code
  path.
- **No statement in `app/bridge` takes `FOR UPDATE`**, and the dispatch module
  imports no session, so commit-before-dispatch cannot be violated by accident.

## What ships

Three tables (`external_capability_grants`, `external_request_nonces`,
`external_gateway_calls`), one nullable column on `agents`, eleven routes under
`/api/v1/bridge`, three permissions, and **one** governed capability —
`http_tool.invoke`, dispatched through M1's egress guard to a real endpoint.

A broad capability catalog and an external-agent SDK are deferred (§25A); the
the command-center UI shipped in 5.8 — see
[`docs/command-center/overview.md`](../command-center/overview.md), where an agent at
GATEWAY_ENFORCED is labelled "authorize boundary calls" and offers no containment
affordance; assurance mapping is 5.9.

## The proof

The end-to-end test runs ACT under a **real uvicorn server on a real socket**
and drives it from a **real external agent in a separate OS process** that
imports nothing from ACT — asserted over that script's own AST. It establishes
a scoped identity, calls a real enterprise capability through the boundary
(authorized by the real `AuthorizationGateway`, with real policy and real cost
applied), is truthfully denied a call its grant forbids, and is refused
entirely once the grant is revoked — while an OBSERVED agent's events ingest
with no enforcement and an ADVISORY agent gets a recommendation with no
enforcement.
