# The governed capability boundary

Phase 5.7 / M5.7. See also [enforcement modes](enforcement-modes.md), [external
identity](external-identity.md) and
[ADR-0021](../architecture/adr/0021-truthful-external-enforcement-modes.md).

An agent running outside ACT can call an enterprise capability **through** ACT.
That call is the one thing ACT can genuinely govern about such an agent, and
this is where it does it.

## The flow

```
External agent
  │  signed request (scoped grant — not an internal principal)
  ▼
rate limit ─────────────────────────────── per grant, per minute
  │
verify signature + consume nonce ───────── COMMIT (a replay loses here,
  │                                         before any work is done)
  ▼
ACT's boundary
  ├─ grant scope ......... narrows; never grants
  ├─ AuthorizationGateway.authorize_agent(agent, capability.authz_action)
  ├─ GovernancePolicyService.resolve(...)   ← the same 4.3 policy rows the
  │                                           engine's checkpoints read
  └─ BudgetService.resolve + utilization    ← the real 4.4 budgets
  │
record the decision ───────────────────── COMMIT  ◀── commit-before-dispatch
  │
  ├─ ALLOW → dispatch through M1's egress guard + http_executor
  │            (no transaction open, no lock held)
  └─ DENY  → truthful denial, audited, nothing dispatched
  │
record what the dispatch did ──────────── short second transaction
```

## It is a boundary, not a second authorizer

`CapabilityBoundary` has no permission logic, no policy evaluation and no
budget arithmetic of its own. It asks the platform's existing authorities and
records what they said. `test_ac04_every_boundary_call_authorizes_through_the_real_gateway`
asserts structurally that the only authorization call it makes is
`AuthorizationGateway.authorize_agent`, and that it never reaches RBAC or ABAC
directly.

The grant's scope is checked **first** and only ever narrows the result. A
scope entry is `{"capability": ..., "target_ref": ...}`; a null `target_ref`
covers every target *of that capability* and is never a wildcard across
capabilities.

## Commit-before-dispatch

The permanent rule, and not theoretical here: the reference capability makes a
real outbound HTTP call. The decision is committed before that call begins, so
no transaction — and therefore no lock — spans it. No statement in `app/bridge`
takes `FOR UPDATE`, and `app/bridge/dispatch.py` imports no session at all.

Both are asserted over the AST, and proven behaviourally: while an outbound
call is in flight, a **second real Postgres connection** reads the committed
gateway record *and writes to it* (`test_ac08_row_is_written_and_readable_while_dispatch_is_in_flight`).
The M1 deadlock required a lock held across dispatch; nothing here can produce
one.

## Fail semantics

Per capability, honouring the M4 §9 plane rule:

| Plane | Capability | On failure |
|---|---|---|
| `GOVERNANCE` | `http_tool.invoke` | **fails closed** — an unevaluable authorization, policy or cost decision **denies**, recorded with `fail_mode=FAIL_CLOSED` and `policy_outcome=UNEVALUABLE` |
| `OBSERVABILITY` | `telemetry.ingest` | **fails open** — a dropped event degrades evidence and blocks nothing |

There is no branch that turns an unevaluable governance decision into an allow.

**When the downstream capability itself is unavailable**, ACT records what
actually happened: the boundary **allowed** the call and the dispatch
**failed** (`dispatch_status=DISPATCH_FAILED`, with the real error). It does not
fake a success, and it does not retroactively rewrite its own ALLOW into a DENY
— ACT did allow it, and pretending otherwise would misrepresent the decision.

A database `CHECK` (`ck_ext_calls_denied_never_dispatched`) makes the converse
unrepresentable: a denied call can never carry a dispatch.

## What is governed — and what is not

ACT does **not** proxy the external agent's model calls or network traffic.
There is no catch-all route, no pass-through path, and no destination a caller
can name. An external agent may call exactly the declared capabilities, against
exactly the targets its grant scopes.

One governed capability ships:

| Key | Plane | Target | Notes |
|---|---|---|---|
| `http_tool.invoke` | GOVERNANCE | a registered HTTP `Tool` | dispatched through M1's egress guard: allowlisted hosts, DNS-pinned connections, no auto-followed redirects, response cap, timeout |

Alongside it is one **observability** capability, `telemetry.ingest`, which is
not a governed call at all: it is the evidence channel behind `/events`, it
enforces nothing, and it may be scoped into a grant in any enforcement mode
(see [external identity](external-identity.md)). The boundary refuses to run an
observability capability through the governance flow, and vice versa.

An external agent gets exactly the egress control a native agent's tool call
gets — ACT does not open a weaker path for a caller it trusts less. The HTTP
method comes from the tool's own declaration, never from caller parameters, so
a caller asking for a read cannot smuggle a delete.

A broad capability catalog and an external-agent SDK are **deferred** (§25A).
One real path proves the boundary better than ten declared ones.

## Cost metering, honestly

The boundary reads the real 4.4 budgets via `BudgetService.resolve` +
`utilization` and denies a call against an exhausted `HARD_LIMIT`.

It deliberately does **not** take a reservation: `ReservationService.reserve` is
keyed to an `AgentExecution`, and a boundary call has none. Fabricating one to
borrow the mechanism would put a lie in the execution ledger. So ACT enforces
the ceiling it can genuinely read and records `NOT_MEASURABLE` where no budget
applies, rather than reporting a number it invented.

For the same reason the 4.3 `RuntimeGovernanceEngine` is not invoked: it decides
for an execution. The boundary reads the same policy rows the engine reads —
reuse of the authority without a fabricated execution.

## The decision record

Every boundary decision writes one `external_gateway_calls` row and one audit
event — `EXTERNAL_GATEWAY_CALL_ALLOWED` or `EXTERNAL_GATEWAY_CALL_DENIED`. A
denial is audited exactly like an allow; a truthful refusal is not a non-event.

The row stores `enforcement_mode_at_time` rather than re-deriving it, because
the question an auditor asks later is "what did ACT claim it could do *when it
decided this*" — a later mode transition must not rewrite the answer.

The downstream response body is never stored. It is the external system's data,
and the record is a governance artefact, not a response cache.
