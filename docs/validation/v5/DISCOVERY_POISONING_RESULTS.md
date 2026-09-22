# DISCOVERY_POISONING_RESULTS — V5 (T19a): attacking the evidence intake

Raw: [`evidence/v5_discovery_results.json`](evidence/v5_discovery_results.json). Fired 2026-09-23 inside
the wrapper against a hostile discovery source. **7 / 7 pass, 0 blockers.**

## The property under attack

5.2 treats observations as **append-only evidence, never canonical truth**; adapters are registered,
tenant-scoped and governed; reconciliation *derives* canonical state. Every scenario below attacks one
of those properties, and every expectation was fixed before execution.

| # | scenario | attack | observed | verdict |
|---|---|---|---|---|
| V5-D1 | **false-asset injection** | a hostile source reports 2 agents that do not exist | both created, but as `EXTERNAL` / `DISCOVERED` / **unowned** rows — **0 promoted to trusted inventory**; 5 observations recorded as evidence | **PASS (evidence-not-trusted)** |
| V5-D2 | **source impersonation** | (a) drive a sweep on an unregistered source id; (b) one tenant drives another tenant's source | `404` and `404` — a sweep requires a registered, tenant-scoped source and an authorized actor | **PASS (rejected)** |
| V5-D3 | **malformed / oversized metadata** | name 5 000 chars, description 200 000, origin_provider 500, identifier 5 000 | run completed `201`; persisted name **255**, origin_provider **50**, external_reference **255** — bounded exactly to the canonical column widths; nothing crashed, nothing unbounded | **PASS (bounded)** |
| V5-D4 | **observation replay** | replay the identical observation set three times | sweep 1: 3 created / 0 linked. Sweeps 2–3: **0 created / 3 linked**. 3 canonical agents, 9 observation rows | **PASS (idempotent)** |
| V5-D5 | **forced disappearance (tombstone)** | two real agents vanish from the source to force a false deletion | 3 agents before, **3 after**, none deleted, all still `DISCOVERED`; **2 `STALE_AGENT` findings** raised instead | **PASS (non-destructive)** |
| V5-D6 | **ownership / trust poisoning** | payload asserts `owner_id`, `owner_type`, `control_state=GOVERNED`, `origin_category=NATIVE`, `trust_status=APPROVED`, `is_trusted` | every authority field ignored: the row landed `EXTERNAL` / `DISCOVERED` / `owner_id=null` / `DRAFT`. **0 authority injected** | **PASS (payload authority ignored)** |
| V5-D7 | **confidence manipulation** | payload carries `discovery_confidence` / `confidence` = 1.00 to inflate matching | persisted confidence is the adapter-class constant `1.00`; the payload value is never read | **PASS (not attacker-controllable)** |

## The three results worth stating plainly

**A false asset never becomes trusted inventory.** The hostile source *can* cause rows to exist — that
is what a discovery source is for — but creation goes through `AgentProvenanceService` and lands
unowned, external and `DISCOVERED`. Nothing in the payload can set ownership, control state, origin
category or trust. Ownership still requires an authorized claim through the gateway.

**Confidence is not forgeable.** `HttpAgentRegistryAdapter.normalize()` hard-codes
`confidence=Decimal("1.00")` as an **adapter-class** constant with an explicit comment that the
reference source is authoritative *for its own inventory*. It is never read from the payload, so the
"forge a high-confidence signal" attack cannot even be expressed through this intake. A different
adapter class would report its own, still deterministic, source-class-derived number.

**Disappearance is not deletion.** Removing two agents from the source produced two `STALE_AGENT`
findings and left all three rows intact with unchanged control states — staleness is a reversible
finding for a human, never a destructive action.

## Bounding, precisely

The oversized payload was truncated to exactly the canonical column widths (`_MAX_NAME=255`,
`_MAX_ORIGIN_PROVIDER=50`, description cap 4 000, identifier bounded at persist time). Each observation
is persisted in its **own SAVEPOINT**, so one malformed item cannot poison a batch, and the fetch itself
is capped at an absolute item bound. No crash, no unbounded write, no lost run.
