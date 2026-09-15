# The Enterprise Agent Command Center

Phase 5.8 / M5.8. The operator surface over everything Phases 5.1–5.7 built —
inventory, discovery, ownership, the authority graph, dependencies and blast
radius, posture and shadow, threats and containment, external governance.

It is the first Milestone 5 phase to touch the frontend, and it carries all the
M5 UI deferred since 5.1.

## What it is, and what it is not

**It reads and triggers. It decides nothing.** Every action dispatches to the
5.1–5.7 endpoint that already owns it — and that endpoint already authorizes,
isolates by tenant, enforces idempotency, writes its own audit, and applies the
truthful-reach rules. The command center adds no domain logic, no enforcement,
no rule and no score.

**It reuses the 3.10 / 4.9 pattern verbatim.** `ConfirmActionDialog` and
`useGuardedAction` are imported from `@/modules/operations`; the persona
vocabulary from `@/modules/observability`. There is no second design system, no
second confirmation dialog, and no second definition of what "Security" means
as a persona.

## The rule that matters most: truthful affordances

Phases 5.1–5.7 spent the whole milestone making ACT honest about reach.
`control_state` is server-authoritative (5.1). Containment is truthfully
*refused* for an agent ACT does not run (5.6). `NATIVE_ENFORCED` is not even
storable — it is derived from `control_state == 'GOVERNED'`, so no row can claim
enforcement ACT lacks (5.7).

The command center is the one surface a human acts from. A button reading
"Suspend" on an agent ACT cannot suspend, or a badge reading "Governed" on a
GATEWAY_ENFORCED agent, would re-introduce exactly the over-claim that work
removed — in the place where it would actually cause harm.

| Agent state | Containment affordance | Label shown |
|---|---|---|
| `NATIVE_ENFORCED` (GOVERNED) | **full** — suspend/terminate via 5.6 | "ACT runs this agent and enforces it in full." |
| `GATEWAY_ENFORCED` (REGISTERED) | **none on the agent**; boundary calls only | "ACT authorizes this agent's capability calls that route through ACT's gateway." |
| `ADVISORY` | **none** | "ACT evaluates policy for this agent and recommends." |
| `OBSERVED` / DISCOVERED | **none** | "ACT observes this agent." |

**The frontend derives none of this.** `affordances.ts` contains no mode name,
no control-state name, and no mode→label map — a test asserts that over the
file's own source. It reads three fields the server computed with 5.7's
`app.bridge.modes`:

```
reaches_agent_execution   → whether to offer containment
reaches_boundary_calls    → whether ACT can refuse this agent's calls
display / limits          → the exact sentences, rendered verbatim
```

A second test scans every file in the module and fails on any
`control_state ===` or `enforcement_mode ===` comparison, because either would
be a second opinion about ACT's reach.

**An unavailable affordance says why.** Containment is not shown greyed-out and
unexplained; it is absent, and the server's own `limits` sentence explains the
absence. A missing control with no reason reads as a broken feature — the
explanation is what makes it read as the truth it is.

## Other truthful-state rules

- **Shadow shows why.** Phase 5.5 made shadow a derived, disputable finding
  with no `shadow` column anywhere. The UI renders the *conditions* — rule,
  severity, reason — never a bare red pill.
- **"Hidden" is not "zero".** Each estate section is probed against its own
  domain permission, and a section the caller cannot read returns
  `visible: false`, rendered as "hidden from you". A `0` in a security
  dashboard reads as "all clear" and would be the most comfortable possible
  lie.
- **Unmeasurable cost is named, not summed.** Boundary calls ACT cannot price
  are counted and labelled `NOT_MEASURABLE` (5.7), never folded into a total
  that would look complete.
- **`INSUFFICIENT_DATA` and `REFUSED` show as themselves.** A refused
  containment is surfaced with its reason, because an operator who believes an
  agent was contained when nothing happened is worse off than one who knows.
- **A failed read shows the failure.** Never an empty state — an empty list and
  a broken backend look identical, and only one is safe to act on.

## The two new endpoints

5.8 adds **no migration, no table and no column**. It adds two read-only
aggregations, for the same reason Phase 4.9 added two:

| Endpoint | Why it cannot be composed client-side |
|---|---|
| `GET /api/v1/command-center/estate` | `GET /runtime/agents` is paginated at 500 rows with no `control_state`/`origin_category` filter and no counts. An estate total over tens of thousands of agents would mean paging the whole table and counting in the browser. |
| `GET /api/v1/command-center/agents` | An inventory row needs its enforcement mode and shadow conditions; per-row lookups would be N+1 requests per page. |

Both are `GET`-only (asserted structurally: no `post`/`put`/`patch`/`delete`
anywhere in the package), tenant-scoped, and compute no domain state — the
posture score comes from 5.5's `PostureSummaryService`, shadow from 5.5's
`ShadowAgentService`, and the mode and reach from 5.7's `app.bridge.modes`,
including its `NATIVE_CONTROL_STATE` constant rather than a re-typed literal.

The **agent drilldown needs no new endpoint**: it composes existing 5.1–5.7
endpoints with react-query, which is orchestration, not logic.

## The views

Thirteen, each with the permission its data needs and the personas (§29) it
serves — see [`personas.ts`](../../frontend/src/modules/command/personas.ts).

AI Estate · Agent Inventory · Shadow AI · Ownership · Identity & Delegation ·
Control Graph · Tools & MCP · Security Posture · Threats & Incidents ·
External Platforms · Governance Coverage · Cost Exposure · Assurance

**Assurance is deliberately empty and says so.** Compliance mapping is Phase
5.9; a placeholder framework grid would imply ACT produces evidence it does not
yet produce, which is the same class of over-claim the rest of this center
exists to avoid.

## Which endpoint feeds which view

| View | Reads |
|---|---|
| AI Estate | `command-center/estate` |
| Agent Inventory, Ownership | `command-center/agents` |
| Agent drilldown | `runtime/agents/{id}`, `bridge/agents/{id}/enforcement-mode`, `posture/agents/{id}/shadow`, `posture/findings`, `graph/agents/{id}/dependencies` |
| Shadow AI | `posture/shadow-agents` |
| Security Posture | `posture/findings` (+ resolve/suppress) |
| Threats & Incidents | `threat/findings`, `threat/containment` |
| External Platforms | `bridge/modes`, `bridge/calls` |
| Control Graph | `graph/blast-radius/unapproved-mcp`, `graph/edges` |
| Identity & Delegation | `graph/edges` |
| Tools & MCP | `graph/mcp-servers` |
| Governance Coverage, Cost Exposure | `command-center/estate` |
| Assurance | — (5.9) |

Guarded actions dispatch to: `runtime/agents/{id}/claim` (5.1),
`posture/findings/{id}/resolve|suppress` (5.5),
`threat/agents/{id}/containment` (5.6),
`bridge/agents/{id}/enforcement-mode` and `bridge/grants/{id}/revoke` (5.7).
