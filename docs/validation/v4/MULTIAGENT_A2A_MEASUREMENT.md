# MULTIAGENT_A2A_MEASUREMENT — V4 (T17 / I-2): the observability map

Raw: [`evidence/v4_multiagent_results.json`](evidence/v4_multiagent_results.json). Measured inside the
wrapper on 2026-09-22 with **real** LangGraph 1.2.12 and CrewAI 1.15.22 multi-agent systems ACT did not
build, climbing Tier 3 → 6.

**The distinction this batch exists to keep separate:** *integrity* (does ACT's own boundary hold when a
framework peer causes a forbidden action?) versus *observability* (can ACT see the A→B relationship that
caused it?). The V4 result is that **integrity holds completely while the A2A edges are entirely
NOT_OBSERVABLE** — the identity/authority analogue of V3's contained-but-not-detected split.

## Why the edges cannot be seen (this is structural, not incidental)

`backend/app/models/graph.py` declares `AGENT_DELEGATES_TO` as an edge type and says so plainly:

> `DELEGATES_TO` / `TRUSTS` / `ACTS_AS` have real producers in Phase 5.3 … **`AGENT_DELEGATES_TO` is the
> declared, producerless** agent→agent type.

There is also **no API that creates one**: the graph exposes `POST /trust-edges` and
`POST /delegation-edges`, and the latter takes only a `delegation_id` and mirrors a *human* delegation
row. So ACT cannot hold an agent-to-agent authority edge for **any** framework, by construction (I-2,
ADR-0017).

## The five questions

| # | question | answer | evidence |
|---|---|---|---|
| **Q1** | What can ACT **see** of externally-created A2A relationships? | **Agents: YES. A2A edges: NOT_OBSERVABLE.** | 3 agents discovered and visible; **14** real framework handoffs performed; **0** `AGENT_DELEGATES_TO` edges; the tenant's edge set stayed empty |
| **Q2** | Does ACT ever **infer** an A2A edge it lacks evidence for? | **NO — zero inferred edges.** | before 0 → after 0 while 14 real handoffs occurred; a fabricated-id probe at the only edge route returned `422`; **0 `AGENT_DELEGATES_TO` rows exist anywhere in the database** |
| **Q3** | Does **per-hop tenant bounding** hold across whatever A2A ACT does observe? | **YES.** | tenant B's reachability query over tenant A's agent returned nothing; every recursive step re-applies `organization_id` and truncates at the tenant edge |
| **Q4** | When a framework peer causes agent B to take a forbidden action, does ACT **contain** it? | **YES — 6/6 contained.** | every forbidden and exfil-shaped boundary call across Tiers 5–6, from both frameworks, denied `403` by grant scope; allowed calls dispatched `200` |
| **Q5** | Can ACT **attribute** the action to the causing peer? | **PARTIAL — acting agent attributed, causing peer NOT_OBSERVABLE.** | each `external_gateway_calls` row names `agent_id` + `grant_id` + target + outcome; the framework-internal peer that decided the action has no linkage in ACT |

## Q2 is the one that could have been a defect — and was not

ACT inferring an A2A edge would be a **false authority claim**: asserting a delegation relationship it
has no evidence for. Across 14 genuine agent-to-agent handoffs in two different frameworks, ACT created
**zero** such edges and offered no route to create one. It left the graph honestly empty rather than
guessing. That is the correct behaviour, and it is recorded as a pass, not as a gap.

## Q5, stated precisely

All Wave-2 workers act under **one** external agent's grant, so ACT observes one acting identity
regardless of which framework peer decided the action. ACT therefore answers "*which governed identity
took this action*" exactly and completely, and cannot answer "*which peer told it to*". The second
question is framework-internal. Nothing in ACT claims otherwise.

## What this sizes

| gap | evidence from this batch | product-change |
|---|---|---|
| **I-2** — no A2A edge producer | 0/14 observability rate; no ingestion path for framework-declared relationships | **O-7** (A2A / agent-card ingestion) |
| cross-agent correlation | a forbidden action is contained and attributed to the acting agent, but not correlated to the causing peer | **O-4** (cross-agent correlation) |

Both are **recorded, not implemented**. The honest headline is that ACT's *boundary* did its whole job
against real multi-agent frameworks while its *graph* stayed truthfully silent about relationships it
has no evidence for.
