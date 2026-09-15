# ADR-0021 — Four enforcement modes, each truthfully bounded; the strongest is derived from `control_state` and is not storable

- **Status:** Accepted
- **Date:** 2026-09-15
- **Deciders:** Phase 5.7 / M5.7 (Milestone 5 — Universal Agent Control & Security Fabric)
- **Supersedes:** — (it does, however, *correct* an anticipation written into
  `Agent.control_state`'s own comment in M5.1; see "The GOVERNED question")
- **Relates to:** ADR-0015 (the universal agent asset model and
  `control_state` — this ADR derives the strongest enforcement mode from it),
  ADR-0020 (truthful containment — this ADR keeps its gate honest rather than
  widening it), ADR-0009 (runtime governance as a fail-closed plane — the
  boundary inherits the fail-closed/fail-open split), ADR-0008 (telemetry as a
  derived plane — why OBSERVED ingest fails open).

## Context

Milestone 5's promise is "govern the AI you didn't build". Phases 5.1–5.6 made
ACT able to *describe* agents it does not run, and 5.6 made containment
**truthful** — an agent ACT does not execute gets a real refusal, never a faked
success. 5.7 is where ACT must actually *do* something to such an agent, and it
is the phase where the milestone's credibility is most easily destroyed.

The failure is specific and seductive: a product that says "governed" about an
agent it can only observe. Every part of the system that then depends on that
word — a dashboard, an audit report, an incident response — inherits a lie. One
over-claiming mode is worth more damage than every feature in the milestone is
worth value.

Three design questions had to be answered without flinching.

### 1. What does ACT actually control?

Only what routes through it. An external agent's model calls, its network
traffic, the tools it holds directly — ACT is not in the path of any of these
and cannot become so without proxying everything. So the honest enforcement
surface is the **capability call the agent chooses to send through ACT**, and
the honest claim is "ACT authorizes this agent's calls through ACT's gateway",
never "ACT governs this agent".

### 2. Should ACT proxy everything, so it *can* claim more?

No. A proxy-everything design is unscalable, lock-in-inducing, and — decisively
— **cannot be truthfully guaranteed**. An agent can always make a call that
does not traverse the proxy, so the guarantee would be false at exactly the
moment it mattered. A narrow claim that is always true beats a broad claim that
is usually true.

### 3. How does an external agent prove identity without becoming internal?

Federation was the obvious candidate and is the wrong one.
`FederationService._resolve_or_provision_user()` provisions a `User` row, maps
group claims to roles, and issues a session. Every federated login mints an
**internal principal with internal authority** — the exact privilege escalation
this phase forbids. A bearer API key (`AgentApiKey`) fails differently: bearer
tokens cannot be replay-protected, because the token is the request's only
proof.

## Decision

**1. Four modes, each with a written, enforced bound.**

| Mode | ACT does | Reach | Cannot |
|---|---|---|---|
| `OBSERVED` | ingests events as evidence (fail-open, scrubbed) | none | deny, stop or constrain anything |
| `ADVISORY` | evaluates the real 4.3 policies, recommends | none | enforce anything; a recommendation is advice for a human |
| `GATEWAY_ENFORCED` | authorizes/denies capability calls routed through ACT | **the boundary only** | reach anything the agent does out of band |
| `NATIVE_ENFORCED` | runs the agent (M1–M4) | full — 4.3 engine + kill switch | — |

Each mode carries a `display` **and** a `limits` string, and both travel in
every API response. A consumer cannot render ACT's claim without also receiving
what ACT cannot do.

**2. The strongest mode is not storable. It is derived.**

`agents.external_enforcement_mode` has a CHECK constraint admitting only
`OBSERVED`/`ADVISORY`/`GATEWAY_ENFORCED`. `NATIVE_ENFORCED` cannot be written
into the database anywhere. The effective mode is computed in one function:

```
control_state == 'GOVERNED'  ->  NATIVE_ENFORCED
otherwise                    ->  external_enforcement_mode  (NULL => OBSERVED)
```

So full enforcement cannot be *asserted*; it has to be *true*, and it is true
exactly when Phase 5.6's containment gate — reading the same column — says it
is. The two phases cannot drift apart, because there is only one signal. This
also means the migration needs no backfill: every pre-existing row already has
a truthful mode the moment the column exists.

**3. The gateway is a boundary, not a second authorizer.**

`CapabilityBoundary` calls the existing `AuthorizationGateway.authorize_agent`,
resolves the existing `runtime_governance_policies` through
`GovernancePolicyService`, and prices against the existing 4.4 budgets through
`BudgetService`. It contains no permission logic, no policy evaluation and no
budget arithmetic of its own. A grant's scope only ever **narrows** what those
authorities would allow; it grants nothing.

**4. External identity is a signed request against a scoped grant.**

HMAC-SHA256 over method, path, timestamp, a single-use nonce and a digest of
the exact body bytes. The secret is stored only as Fernet ciphertext
(M4.11 `credential_crypto`). Replay protection is the
`(grant_id, nonce)` unique constraint — the database, not a cache, so two
concurrent replays cannot both win. No `users` row, no role, no session.

**5. Commit before dispatch.** The boundary decides, records and commits
*before* the downstream call. No statement in `app/bridge` takes `FOR UPDATE`.
This is not theoretical here as it was in 5.6: the reference capability makes a
real outbound HTTP call through M1's egress guard.

**6. One governed capability ships.** `http_tool.invoke`. No catch-all route,
no pass-through, no destination a caller can name. A broad catalog and an
external-agent SDK are deferred.

### The GOVERNED question

M5.1's comment on `control_state` anticipated that external agents would reach
`GOVERNED` "at NATIVE/GATEWAY enforcement, which is Phase 5.7". Building 5.7
showed the GATEWAY half of that would have been a **false claim**, so this ADR
deliberately does not do it.

`GOVERNED` means *ACT runs and enforces this agent* — which is precisely what
Phase 5.6 relies on when it trips the kill switch or terminates an execution.
Promoting a GATEWAY_ENFORCED external agent to `GOVERNED` would have made
5.6's `SUSPEND_AGENT` report success for an agent ACT cannot suspend: an
over-claim manufactured inside the very mechanism built to prevent one.

So a GATEWAY_ENFORCED external agent stays at `REGISTERED`, and 5.6 keeps
refusing enforcement-requiring containment on it — **correctly**. The 5.1
comment has been updated to record this rather than left to mislead.

The consequence is deliberate and worth stating plainly: at GATEWAY_ENFORCED,
ACT's only enforcement reach beyond a single call is **revoking the grant**,
which ends the agent's ability to use ACT's boundary and does not stop the
agent. 5.7 therefore does **not** add an eighth containment action to 5.6's
exhaustive seven; `ExternalGrantService.revoke` is the seam a later phase can
wire in if that proves useful.

## Consequences

**Good.**
- No mode can claim reach ACT lacks, and the strongest claim is structurally
  unwritable — enforced by a CHECK constraint, not by reviewer vigilance.
- 5.6 is untouched and still truthful; the two phases share one signal.
- No new authorization system, no parallel enforcer, no second agent registry.
- A compromised grant costs exactly its scoped capabilities on one agent in one
  tenant, is revocable immediately, and cannot escalate to internal identity —
  because there is no path from an external grant to a `User`.
- Commit-before-dispatch is proven behaviourally against a real second Postgres
  connection while a real outbound call is in flight.

**Costs, accepted.**
- **GATEWAY_ENFORCED is genuinely narrow.** Customers who expect "governed"
  to mean "controlled" will find the claim smaller than they hoped. That is the
  point: the smaller claim is the true one.
- **Cost metering is a ceiling check, not a reservation.**
  `ReservationService.reserve` is keyed to an `AgentExecution` a boundary call
  does not have, and fabricating one would corrupt the 4.4 ledger. So the
  boundary enforces the limit it can genuinely read and records
  `NOT_MEASURABLE` where no budget applies, rather than inventing a number.
- **The 4.3 engine is not invoked at the boundary**, for the same reason — it
  decides for an execution. The boundary reads the same policy rows the engine
  reads, which is reuse of the authority without a fabricated execution.
- **One capability is a small surface.** Deliberate: one real path proves the
  boundary better than ten declared ones.

## Alternatives rejected

- **Proxy all model/network traffic.** Rejected: unscalable, lock-in-inducing,
  and not truthfully guaranteeable.
- **Federation for external-agent identity.** Rejected: provisions internal
  principals with roles and sessions.
- **A bearer API key.** Rejected: cannot be replay-protected.
- **Storing `NATIVE_ENFORCED` as a settable value.** Rejected: it would make
  over-claiming a one-column write away.
- **Promoting GATEWAY_ENFORCED agents to `GOVERNED`.** Rejected: it would make
  Phase 5.6 lie. See "The GOVERNED question".
- **An eighth containment action in 5.6.** Rejected for this phase: it would
  alter a reused authority whose action set is documented as exhaustive.
