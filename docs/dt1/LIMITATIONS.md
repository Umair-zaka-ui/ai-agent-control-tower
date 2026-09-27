# DT1 — Limitations of the current ACT architecture that the estate exercises (technical / evidence record)

These are **evidence and control boundaries in the live code as re-verified at grounding on 2026-09-27**
(`SCHEMA_GROUNDING.md`, "Gap re-verification"), recorded so Stage 2 can derive truthful absences instead of pre-declaring
them. They belong in the technical deep dive, the evidence pack and this document. **None of them is the primary
five-minute buyer demo's hero**; that demo (not built in Stage 1) focuses on estate, shadow discovery, blast radius,
authority, truthful refusal, real effect-verified containment, evidence provenance and the design-partner invitation.

| id | status at grounding | boundary (with code reference) | how the estate carries it |
|---|---|---|---|
| **F6-1** | PRESENT | All six threat rules (`app/threat/rules.py`) read `AgentExecution` / `RuntimeGovernanceDecision` / `ToolCall`; nothing in `app/threat` reads `external_gateway_calls`, where a gateway-enforced agent's denials are recorded (`app/bridge/gateway.py`). Enforcement is complete and detection is silent for that agent class. | 6 F6-1-relevant agents whose real processes attempt out-of-scope gateway targets. |
| **I-1** | PRESENT (scan tightened: the first pattern also matched `RequestContextMiddleware`) | No table or model represents an agent's runtime memory/context state; the nearest field is `agent_definitions.memory_requirements`, a declared requirement, not observed state. | 6 agents with persistent memory (store, retention) recorded as facts. |
| **I-2** | PRESENT | `AGENT_DELEGATES_TO` is declared in `EDGE_TYPES` (`app/models/graph.py`) and walked by `_delegation_prefix`, but no code path creates such an edge and no A2A ingestion exists. | 6 real handoffs (LangGraph, CrewAI, HTTP A2A) and 5 agent-authority facts. |
| **F-2** | PRESENT | `reconstruct_authority_chain` starts `FROM agent_executions` (`app/graph/traversal.py`); gateway-enforced external agents produce none — attribution is by grant and issuer, not by chain. | Every gateway-enforced agent. |
| **V9-1** | PRESENT | The reachability CTE's path-array cycle guard (`traversal.py`, `ANY(r.path)`) enumerates simple paths — exponential on branching trust graphs; default depth 16, cap 32. | Agent-authority/TRUSTS facts exist but the estate's trust graph is deliberately small; the class is recorded in the contract as PARTIALLY_OBSERVE with its precondition. |

Related, recorded for Stage 2's readiness rather than as estate conditions: **O-11** (the backend image build embeds
`backend/.keys/`) and the absence of a platform-level `OBSERVE_ONLY` switch — both belong to the V10 prerequisites, not to
the Digital Twin.

If any of these changes in a later build, `grounding.py` re-derives `gap_status` from the evidence, the affected
observability-contract entries change classification, and the estate keeps the objective condition. Nothing is preserved
"for the demo".
