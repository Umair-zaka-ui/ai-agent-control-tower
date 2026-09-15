# Enforcement modes — what ACT can and cannot do to each agent

Phase 5.7 / M5.7. See also [the gateway](gateway.md), [external
identity](external-identity.md) and
[ADR-0021](../architecture/adr/0021-truthful-external-enforcement-modes.md).

ACT governs agents it did not build and does not run. The whole value of that
depends on ACT being honest about **how far** its control actually reaches. One
mode that claims more than it delivers would poison every dashboard, audit
report and incident review downstream of it.

So each mode below carries two sentences, and both travel together in every API
response: what ACT does (`display`), and what ACT cannot do (`limits`).

## The four modes

| Mode | ACT does | Enforcement reach | ACT explicitly cannot |
|---|---|---|---|
| `OBSERVED` | ingests events as evidence (fail-open, scrubbed) | **none** | deny, stop or constrain anything the agent does |
| `ADVISORY` | evaluates the real Phase 4.3 policies and recommends | **none** | enforce anything — a recommendation is advice for a human |
| `GATEWAY_ENFORCED` | authorizes or denies capability calls the agent routes *through ACT* | **the boundary only** | reach the agent's model calls, its network traffic, or any tool it holds directly |
| `NATIVE_ENFORCED` | runs the agent (M1–M4) | **full** — the 4.3 engine and the kill switch | — |

The sentence ACT is permitted to use for GATEWAY_ENFORCED is:

> ACT authorizes this agent's capability calls that route through ACT's gateway.

Never "ACT governs this agent". A test (`test_ac03_no_mode_claims_reach_act_lacks`)
asserts that no non-native mode's text contains a claim of governing or
controlling the agent itself.

## The mode is derived, not declared

There is one function that answers "what enforcement does ACT have over this
agent" — `app.bridge.modes.effective_mode`:

```
control_state == 'GOVERNED'  ->  NATIVE_ENFORCED
otherwise                    ->  external_enforcement_mode   (NULL means OBSERVED)
```

`agents.control_state` is Phase 5.1's server-authoritative signal, and it is the
**same** column Phase 5.6's truthful-containment gate reads. Deriving the mode
from it means the two phases cannot disagree about whether ACT really enforces
an agent.

The other half is a database constraint. `agents.external_enforcement_mode`
admits only `OBSERVED`, `ADVISORY` and `GATEWAY_ENFORCED`:

> **`NATIVE_ENFORCED` cannot be written into the database anywhere.**

Full enforcement cannot be asserted by setting a column. It has to be true.
Attempting to assign it returns `EXTERNAL_MODE_NOT_SETTABLE`, which explains
that the mode is derived from `control_state` and points at the agent
control-state workflow instead.

This also means the 5.7 migration needs **no backfill**: every pre-existing row
gets a truthful mode the instant the column exists — native agents are
`GOVERNED` and therefore `NATIVE_ENFORCED`; discovered, claimed and registered
agents are `OBSERVED`, the weakest truthful claim.

## Why a GATEWAY_ENFORCED agent is not `GOVERNED`

M5.1's own comment on `control_state` anticipated that external agents would
reach `GOVERNED` "at NATIVE/GATEWAY enforcement, which is Phase 5.7". Building
5.7 showed that the GATEWAY half of that would have been a false claim, so it
is deliberately not done.

`GOVERNED` means *ACT runs and enforces this agent*. That is exactly what Phase
5.6 relies on when it trips the kill switch or terminates an execution. If a
GATEWAY_ENFORCED external agent were marked `GOVERNED`, 5.6's `SUSPEND_AGENT`
would report success for an agent ACT cannot suspend — an over-claim
manufactured inside the very mechanism built to prevent one.

So a GATEWAY_ENFORCED external agent sits at `REGISTERED`, and 5.6 keeps
truthfully refusing enforcement-requiring containment on it.

The honest consequence: **at GATEWAY_ENFORCED, ACT's only enforcement reach
beyond a single call is revoking the grant.** That ends the agent's ability to
use ACT's boundary. It does not stop the agent, and ACT does not say it does.

## Transitions

Setting a mode is server-authoritative: the client sends a *requested* target,
and `EnforcementModeService` validates it.

- Only `OBSERVED`, `ADVISORY` and `GATEWAY_ENFORCED` are assignable.
- A `GOVERNED` agent cannot be assigned a weaker mode — recording one would
  *understate* the control ACT genuinely has, which is untruthful in the other
  direction.
- Re-asserting the current mode is idempotent and emits no transition audit
  event for a transition that did not happen.
- **Dropping below `GATEWAY_ENFORCED` revokes that agent's live grants in the
  same transaction.** Leaving them would leave credentials for a boundary that,
  for this agent, no longer enforces anything.

Every transition is audited (`EXTERNAL_ENFORCEMENT_MODE_CHANGED`) with the
previous mode, the new mode, the `control_state` at the time, the reason and
any grants revoked as a consequence.

## Permissions

| Code | Grants |
|---|---|
| `external_governance.view` | read modes, grants and gateway decision records |
| `external_governance.manage` | set a mode, run an advisory evaluation |
| `external_grant.issue` | issue or revoke a capability grant |

`external_grant.issue` is a **distinct, stronger** code, never implied by view
or manage — the same reasoning that made `containment.execute` its own code in
5.6. It is the one permission that creates an outside party's ability to reach
enterprise capability at all.

## OBSERVED is a working mode, not a label

An `OBSERVED` agent cannot be granted a *governed* capability — that would be a
credential for a boundary that, for it, enforces nothing. It **can** be granted
an evidence-only scope (`telemetry.ingest`) and submit events to `/events`,
because ingesting evidence enforces nothing and implies no control. Without
that, the mode whose entire content is "ACT sees this agent" would have no way
for the agent to be seen. Ingest is fail-open, scrubbed, and returns
`enforcement_performed: false` in its own response contract.
