# MEASUREMENTS — V4, identity/authority **integrity** vs A2A **observability**

Raw: [`evidence/v4_identity_results.json`](evidence/v4_identity_results.json),
[`evidence/v4_delegation_results.json`](evidence/v4_delegation_results.json),
[`evidence/v4_multiagent_results.json`](evidence/v4_multiagent_results.json).

V3's central split was *containment vs detection*. V4's is **integrity vs observability**: ACT's own
identity and authority model held completely, while relationships created inside external frameworks
remained entirely invisible to it. The two are reported separately and never averaged together.

## Integrity metrics (did the model hold?)

| metric | value |
|---|---|
| **identity-rejection rate** (forged / replayed / stale / tampered / expired / revoked / unknown-key) | **10 / 10** |
| external → internal identity escalation | **0** (5 internal endpoints probed with a valid signed identity, none authenticated) |
| gateway bypass | **0** (3 bypass shapes, all `401`) |
| identity substitution contained **and** correctly attributed | yes (`403`, attributed to the signing agent) |
| machine-identity collision granting another's authority | **0** (2 distinct agent rows; B→A's target `403`) |
| **delegation-integrity rate** (forgery, amplification, cross-tenant, revoked, laundering, truncation, depth, replay, cross-tenant chain) | **8 / 9** |
| forgeable / amplifiable / launderable / silently-truncatable authority chain | **none** — all four P1 flags false |
| chain-reconstruction completeness (control) | 3 hops `complete=true`; with a delegation prefix 4 hops `complete=true`; no chain ever claimed completeness while short |
| **per-hop tenant bound** | **100 %** — cross-tenant delegatee edge `404`, cross-tenant chain `404`, cross-tenant reachability empty |
| cycle safety | terminated in **7.6 ms** on an A→B→A cycle |
| **boundary containment for framework-caused forbidden actions** | **6 / 6** (`403`, both frameworks, Tiers 5–6) |
| false-positive blocks on benign actions | **0** (every allowed call dispatched `200`) |
| **canary escapes** | **0** (`{}` unexpected tokens in ACT's records; ACT log 549 lines, 0 canary markers, 0 tracebacks) |

## Observability metrics (can ACT see it?)

| metric | value |
|---|---|
| real framework A2A handoffs performed | **14** (LangGraph + CrewAI, Tiers 3–6) |
| **A2A-edge observability rate** | **0 / 14** — `AGENT_DELEGATES_TO` is declared but producerless |
| `AGENT_DELEGATES_TO` rows anywhere in the database | **0** |
| A2A edges **inferred without evidence** | **0** — no false authority claim |
| attribution of a framework-caused action | **partial**: acting agent + grant attributed; causing peer NOT_OBSERVABLE |
| authority-chain coverage of external agents | **none** — external agents produce 0 `agent_executions`, so the 5.3 chain surface does not apply to them (they are attributed via `external_gateway_calls` instead) |

## Capability ladder

| tier | gate | frameworks executing |
|---|---|---|
| 3 | PASS | LangGraph + CrewAI |
| 4 | PASS | LangGraph + CrewAI |
| 5 | PASS | LangGraph + CrewAI |
| 6 | PASS | LangGraph + CrewAI |

Max tier reached **6**, each gated on the previous tier's boundary result.

## Baseline comparison

| | V2 | V3 | V4 |
|---|---|---|---|
| canary escapes | 0 | 0 | **0** |
| per-hop tenant bound | held | held | **held (100 %)** |
| boundary containment of forbidden actions | n/a (no attacks) | 11/11 (injection) | **6/6 (framework-caused)** |
| false positives | 0 | 0 | **0** |
| the phase's split | — | contained **but not detected** | held **but not observable** |

Timing: the identity batch ran in ~2 s and the delegation batch in ~3 s (pure API work); the multi-agent
ladder took ~75 s wall, dominated by framework start-up across eight agent processes. No containment
latency is reportable because every denial is synchronous with the gateway decision.
