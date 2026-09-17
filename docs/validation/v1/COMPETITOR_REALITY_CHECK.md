# COMPETITOR_REALITY_CHECK — v1.0 (2026-09-18)

Retrieved current material only (register rows cited). ACT side = live code at `2b4f57b`. Default is
`INSUFFICIENT EVIDENCE`; every `ACT BETTER` / `ACT WORSE` carries evidence on both sides. No marketing
claims; where a platform already does something better than ACT, it says so.

| capability | Microsoft (Agent 365 / Entra Agent ID / Defender / Purview) — R-045 R-046 | AWS (AgentCore) — R-047 | Google (Agent Platform / SAIF / Model Armor) — R-048 R-049 | OpenAI / Anthropic — R-040 R-042 | Independent (ServiceNow AI Control Tower R-063, Cloudflare R-054, xAI R-065/066) | ACT (live) | classification |
|---|---|---|---|---|---|---|---|
| Inventory / discovery of agents across the estate | Entra: all agent identities incl. third-party via SDK sidecar / workload federation; "shadow agents" visible | not claimed on retrieved page | Agent Platform registry (names only) | not applicable (they are the platform) | ServiceNow: 30 discovery integrations across AWS/GCP/Azure/SAP/Oracle/Workday (press release) | 5.2 discovery with **one** adapter (HTTP registry); reconciliation is evidence-based, no silent merge (proven) | **ACT WORSE** on breadth (1 adapter vs Microsoft/ServiceNow multi-platform coverage — R-046, R-063 vs `app/discovery/adapters/`); ACT's reconciliation *discipline* is not comparable from retrieved material |
| Truthful control state (never claiming enforcement it lacks) | Entra describes governed identity for third-party agents; no retrieved statement about refusing to claim enforcement | Policy enforced only at the AgentCore Gateway boundary (deterministic, outside agent code) | SAIF: identity propagation should reach every tool | — | ServiceNow: "kill switch via AI Gateway for MCP transactions" — scope of what can actually be stopped not stated | 5.6 REFUSED where no authority; 5.7 non-storable NATIVE_ENFORCED; V0.2 GOVERNED ⇔ NATIVE, all proven by tests | **ACT DIFFERENT** — ACT makes reach-truthfulness structural; no retrieved competitor material describes an equivalent refusal semantics, and absence of a statement is not evidence of absence |
| Policy enforcement at the agent→tool boundary | Defender: "block malicious tool invocations in real time" | Cedar/Dogwood policies at the gateway, incl. **session-temporal** conditions and guardrail-score inputs | Agent Gateway + Model Armor screen tool calls | OpenAI: tool guardrails + approval interruptions | Cloudflare WriteGuard for MCP servers | 4.3 engine per action (native); 5.7 CapabilityBoundary (external, one governed capability `http_tool.invoke`); no temporal conditions | **ACT WORSE** on policy expressiveness vs AWS temporal/session policies (R-047 vs `app/runtime/governance/policies.py`); **INSUFFICIENT EVIDENCE** vs the others |
| Prompt-injection defence | Defender detection + Purview DLP (capability names) | Guardrails "prompt attack" scores feed policy | Model Armor inspects inputs/outputs; SCC "AI Protection" | OpenAI built-in injection/jailbreak guardrails; Anthropic classifiers on untrusted content | — | none (G-1); action bounding only | **ACT WORSE** — every retrieved platform ships a content-level control; ACT's own code records the gap (R-071) |
| Identity for agents | Agent identities + blueprints, conditional access, risk detection, logs; MCP/A2A/OAuth support | AgentCore Identity (IAM, OAuth 2.1, API keys; credential exchange) | Agent Identity (name only) | — | xAI: bots act as the signed-in member, SSO | 5.1 canonical agent + M4 machine identity; external agents get a scoped HMAC grant, never an internal principal (ADR-0021) | **ACT DIFFERENT** (deliberately no principal for external agents); breadth of conditional-access/risk features **INSUFFICIENT EVIDENCE** to rank |
| Containment / kill switch | Defender "block" | policy deny at gateway | — | — | ServiceNow: disable model and tool access via AI Gateway in real time | kill switch (EXECUTION/AGENT/PROJECT/PLATFORM) with dominance proven; grant revocation for external | **INSUFFICIENT EVIDENCE** — no retrieved competitor material states what happens when the platform does not run the agent, which is the property ACT proves |
| Posture / shadow findings | Defender agent posture management, attack paths | — | — | — | ServiceNow risk frameworks (NIST/EU AI Act) | 16 deterministic posture rules; shadow as disputable finding; assurance evidence never a verdict | **INSUFFICIENT EVIDENCE** |
| Data protection for agent I/O | Purview labels, DLP, audit, eDiscovery, retention | — | Model Armor output screening | — | xAI ZDR | none at content level (telemetry privacy scrubbing only, 4.8) | **ACT WORSE** — Purview's agent DLP/labels have no ACT counterpart (R-045 vs `app/telemetry_privacy`) |
| MCP-specific controls | Entra supports MCP for agent auth | Gateway secures MCP-exposed tools | — | Anthropic reviewed MCP directory standards | Cloudflare WriteGuard, shadow-MCP detection (via secondary only); ServiceNow AI Gateway for MCP | 5.4 MCP inventory + trust evidence; no description integrity (G-3) | **ACT WORSE** on MCP-specific controls (R-054 secondary, R-063 vs `app/graph` MCP model); **INSUFFICIENT EVIDENCE** on quality of theirs |
| Audit / evidence export | Purview audit, eDiscovery | CloudWatch decision logs | observability APIs | — | xAI action recording 90 days | 4.1 audit + 4.6 OTel + 5.9 signed DSSE evidence bundles with INSUFFICIENT_EVIDENCE first-class | **ACT DIFFERENT** — signed evidence bundles with explicit insufficiency are not described by any retrieved competitor; ranking would need their evidence formats |
| Human oversight / approvals | — | temporal "approval before transfer" conditions | — | OpenAI "always enable tool approvals" with MCP; Anthropic plan mode + pause-to-ask | Cloudflare human-in-the-loop approvals; xAI Auto Review | approval funnel via 4.3/5.6; no flood/dedup or payload binding (G-7) | **ACT WORSE** vs AWS payload/temporal binding (R-047); others **INSUFFICIENT EVIDENCE** |

## Every `ACT WORSE`, with both sides

1. **Discovery breadth** — Microsoft (R-046: third-party agents via sidecar/federation) and ServiceNow
   (R-063: 30 integrations) vs ACT `app/discovery/adapters/http_agent_registry.py` (the only adapter).
2. **Policy expressiveness** — AWS AgentCore temporal/session conditions (R-047) vs ACT 4.3 per-action
   policies with no session-history predicates.
3. **Prompt-injection defence** — OpenAI/Anthropic/Google/AWS/Microsoft all describe a content-level
   control (R-042, R-040, R-048, R-047, R-045) vs ACT none (R-071 evidence-gap note).
4. **Agent data protection** — Purview DLP/labels for agents (R-045) vs ACT telemetry scrubbing only.
5. **MCP-specific controls** — Cloudflare/ServiceNow MCP gateways (R-054, R-063) vs ACT inventory-only MCP model (G-3).
6. **Approval binding** — AWS temporal approval conditions (R-047) vs ACT approvals without payload binding (G-7).

## No `ACT BETTER` classification is made

The properties ACT can prove (truthful refusal, non-storable enforcement, evidence-not-verdict) have no
retrieved competitor statement to compare against; that is `ACT DIFFERENT`, not `BETTER`. Claiming
otherwise would be the marketing claim this check forbids.
