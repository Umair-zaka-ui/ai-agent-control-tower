# GROUND_TRUTH_MANIFEST — the true picture, recorded before any poisoning

Raw: [`evidence/v5_ground_truth.json`](evidence/v5_ground_truth.json). Recorded 2026-09-23 inside the
V2.1 egress-deny wrapper, before the first hostile sweep.

Without a known-correct picture, "did reconciliation merge correctly?" and "is this blast radius
right?" cannot be answered — only "did it return something?". This manifest is what every V5 result is
scored against.

## True inventory (§1)

The hostile source's `baseline` scenario serves **exactly the three real Wave-1 lab agents**, with the
same identifiers the honest registry publishes. That is the known-correct asset set.

| # | true external reference | true name |
|---|---|---|
| 1 | `lab://wave1/python-agent/<build>` | Lab Python Agent |
| 2 | `lab://wave1/node-agent/<build>` | Lab Node Agent |
| 3 | `lab://wave1/mcp-client/<build>` | Lab MCP Client Agent |

**True agent count: 3.**

## True landing state

Every discovered agent landed identically, and this is the baseline "not trusted" state that
false-asset promotion is measured against:

| property | value |
|---|---|
| `origin_category` | `EXTERNAL` |
| `control_state` | `DISCOVERED` |
| `owner_id` | `null` (unowned) |
| `lifecycle_status` | `DRAFT` |

**Definition used throughout V5:** an agent counts as *trusted inventory* if it is anything more than
this — a non-`DISCOVERED` control state, a `NATIVE` origin, or a non-null owner. A false asset that
merely exists as an unowned `EXTERNAL`/`DISCOVERED` row is **evidence**, not trusted inventory.

## True graph (for the T20 blast-radius scoring)

Constructed deliberately so its reachability set is known exactly:

```
AGENT(python agent) --DEPENDS_ON_TOOL--> TOOL(v5 tool) --TOOL_ACCESSES_RESOURCE--> RESOURCE(payroll)
AGENT(node agent)   -- no path --
RESOURCE(unrelated) -- no recorded dependencies --
```

| question | true answer |
|---|---|
| agents that truly reach the payroll resource | **exactly 1** — the python agent |
| agents that truly reach the unrelated resource | **0** |
| true path | `AGENT → TOOL → RESOURCE` |

Under-estimation (a real dangerous path reported as safe) is the blocker; over-estimation is recorded
separately. Both were measured against this manifest.

## Control of the poisoned source

The hostile registry ([`lab/services/hostile_registry.py`](../../../lab/services/hostile_registry.py))
serves the same wire shape as the honest one, so ACT's real `HTTP_AGENT_REGISTRY` adapter fetches it
over a real socket, but the payload is attacker-chosen per scenario. Its `/_control` plane is refused
unless `ACTLAB_ALLOW_ADVERSARIAL` is exactly `V5`, so it cannot be driven adversarially outside this
authorized phase. Each poisoning scenario runs in its own **fresh tenant**, so scenarios cannot
contaminate one another's ground truth.
