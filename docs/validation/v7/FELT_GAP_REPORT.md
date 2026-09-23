# FELT_GAP_REPORT — where the known gaps actually bite when real agents do real work

This is the analytical deliverable of V7. V3–V6 established that several observability weaknesses
exist. The question here is which are **operationally material** under real workloads and which are
**theoretical**, so the O-1…O-11 roadmap can be prioritised by impact rather than by existence.

Evidence: [`evidence/v7_interop_results.json`](evidence/v7_interop_results.json),
[`evidence/v7_measurements.json`](evidence/v7_measurements.json).

## Summary: which gaps bite

| gap | origin | felt under real work? | severity of the *felt* impact |
|---|---|---|---|
| **F6-1** detection does not cover gateway-enforced agents | V6 | **YES — acutely** | **Material.** The single most consequential gap found in the whole programme |
| **I-2** no A2A edge producer | V4, ADR-0017 | **YES — but bounded** | Moderate. Visible immediately, harmful only for multi-agent forensics |
| **I-1** no memory/context modelling | V3 | **Not felt in V7** | Latent. Nothing in this workload exercised persistent agent memory |
| **F5-2** no cross-identifier correlation | V5 | **Not felt in V7** | Latent. No agent changed identifier mid-run |
| **F-2 / T8-13** no authority chain for external agents | V4 | **YES — quietly** | Moderate. Felt as an absence rather than an error |

## F6-1 — material, and worse under real workload than in isolation

**What happened.** Seven agents ran the full tier ladder. Between them they made **39 boundary calls
that ACT denied** — every single one contained, `403`, correctly. Threat findings raised: **zero**.

**Why.** All six threat rules key off ACT-run execution signals. `governance_denial_spike` counts
governance decisions joined to `agent_executions`, and a gateway-enforced external agent produces no
executions at all. Its denials live in `external_gateway_calls`, which the threat plane never reads.
The rule's threshold is 3; the workload produced 39 denials; the join still returns 0.

**Why this is worse in practice than it looked in V6.** In V6 this was one probe producing one number.
Under V7's real workload the shape of the gap becomes clear: **the agents ACT is most likely to be
governing in an enterprise — independent, framework-built, gateway-enforced — are exactly the agents
its detection plane cannot see.** A security team watching this tenant would have seen a clean board
while seven agents probed a forbidden capability 39 times. Enforcement worked perfectly and told
nobody.

**The honest counterweight:** nothing was missed in the *containment* sense. Every attempt was denied,
attributed to an agent and grant, and recorded in `external_gateway_calls`. The data exists; the
detection plane simply does not consume it. That makes this a **wiring gap, not an architectural one**
— which is precisely why it should be prioritised: the fix is bounded and the payoff is large.

## I-2 — felt immediately, bounded in consequence

**22 real agent-to-agent handoffs** happened across four different mechanisms (LangGraph state edges,
CrewAI task delegation, an OpenAI Agents SDK handoff, an Anthropic SDK message handoff). ACT observed
**zero** A2A edges and inferred **zero**.

Felt as: you can see each agent and every boundary call it makes, but you cannot answer "which peer
caused this?" for any multi-agent system. For a single-agent estate this is invisible; for a
multi-agent estate it is the difference between "agent B did something forbidden" and "agent A told
agent B to". V7 confirms the behaviour is **correct** (no edge is invented), and confirms the cost is
real once frameworks actually delegate.

Bounded because the boundary still held: every framework-caused forbidden action was contained
regardless of which peer caused it.

## F-2 — felt as a quiet absence

External agents produce no `agent_executions`, so the 5.3 authority-chain surface does not cover them.
In V7 this is felt indirectly: the richest attribution available for seven real agents doing real work
is the gateway call record (agent + grant + target + outcome). That is genuinely useful and genuinely
truthful — but "who ultimately authorised this action" is answered by the grant and its issuer, not by
a reconstructed chain. Nobody gets a wrong answer; some questions simply cannot be asked.

## I-1 and F5-2 — latent in this workload

Neither bit. No agent in V7 used persistent memory across sessions, and no agent changed its external
identifier mid-run. They remain real gaps with real threat models behind them (V3 measured I-1
deliberately), but **V7 provides no evidence that they are currently material**, and saying so is more
useful than implying every known gap is equally urgent.

## Re-prioritisation implied by felt impact

1. **F6-1 — highest.** Bounded fix, large payoff, and it silently undermines monitoring of exactly the
   agent class ACT is built to govern.
2. **I-2 (→ O-7) — next.** Real multi-agent estates make it felt immediately; ingestion of
   framework-declared relationships (never inference) is the shape of the fix.
3. **F-2 attribution scope — documentation first.** State plainly that external actions are attributed
   by grant rather than chain, so the absence is expected rather than surprising.
4. **I-1, F5-2 — keep on the roadmap, do not front-load.** No felt impact in this workload.
