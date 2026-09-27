# DT1 — Stage-2 readiness (what Stage 1 hands over; Stage 1 instantiates nothing)

## Assets that must become genuine independent processes (`ACTIVE_REAL_PROCESS_REQUIRED_STAGE2`, 15 agents)

Every gateway-enforced or shared-grant agent and every A2A participant: Vendor Onboarding Assistant (healthy, control
group), Finance Data Connector, Finance Close Orchestrator + Ledger Reconciler Worker + Variance Explainer Worker
(LangGraph state edges), Recruiting Crew Manager + Candidate Sourcer + Interview Scheduler (CrewAI delegation), Treasury
Payment Scheduler, Vendor Portal Sync Bot (vendor-operated), Employee Q&A Copilot, HR Helpdesk Agent (A2A callee),
Budget Forecaster (A2A callee), and the **Finance Research Assistant** (the shadow process that calls the gateway with
`Finance Data Connector`'s grant). The exact list: `agents[].reality_class == "ACTIVE_REAL_PROCESS_REQUIRED_STAGE2"` in
`estate_truth.json`. The V7 lab agents (`lab/agents/v7/`) already implement the LangGraph / CrewAI / custom stacks with
the uniform tier protocol and are the natural substrate.

## Services that must exist (`REAL_EXTERNAL_SERVICE_REQUIRED_STAGE2`, 9 agents + 3 sources)

- **Enterprise Agent Registry (HTTP)** — a real `http.server`-class process serving the paginated `{items, next_offset}`
  shape for the 25 enterprise registry-discoverable agents (`discovery_sources[].lists_agent_ids`); this is the guaranteed
  process/network-boundary crossing for discovery.
- **Cloud Agent Inventory (Bedrock Agents, us-east-1)** — the `AWS_BEDROCK_AGENTS` adapter's `ListAgents` wire shape for
  the 6 cloud-discoverable agents (`bedrock-agent:us-east-1:<id>`); a faithful mock as in V7.5, or a read-only sandbox if
  one is authorized (none existed for V8).
- **Contoso Agent Registry (HTTP)** — the isolation-control tenant's source (lists 1 agent).
- The 7 MCP servers and 21 tools as real endpoints only to the extent the gateway/dispatch proofs need targets (V4/V6
  used loopback HTTP capability servers).

## What Stage 2 must evaluate (derived, never hand-authored)

For every fact class in `observability_contract.json`, derive the expectation from `estate_truth` + the contract and
compare with what ACT actually recorded:

1. **Discovery accuracy vs truth** — registry- and cloud-discoverable agents appear as `DISCOVERED` with exact
   `external_reference` matches; dark shadows (5) do not (a truthful absence: `NOT_OBSERVE`, justified by the fixed adapter
   registry); the NATIVE collision (`vendor-master-sync`) yields a `RECONCILIATION_AMBIGUOUS` finding, never a merge.
2. **Posture specificity** — the 12 control-group agents should produce no serious finding; the 16 rules against the
   conditioned agents should produce the findings whose inputs are ACT-observable (unowned, unapproved MCP/tool, stale or
   expired ACT-held credentials, dormant-with-credential) and *not* those whose inputs are outside ACT (external
   credential over-privilege — `NOT_OBSERVE`).
3. **Blast radius vs `sensitive_reachability`** — for each of the 78 paths, observable iff every hop is a recorded edge
   (Stage 2 must record the DECLARED edges it chooses to load; any unloaded hop is a truthful `incomplete`).
4. **Gateway enforcement (effect-verified)** — the 12 enforced agents' in-scope calls dispatch, out-of-scope attempts are
   denied and never dispatched; the shared-grant shadow's calls are attributed to `Finance Data Connector`
   (`PARTIALLY_OBSERVE`, recorded objectively).
5. **F6-1 derivation** — for the 6 F6-1-relevant agents, threat findings for repeated denials: `NOT_OBSERVE` per the
   contract; Stage 2 verifies the absence *and* that `external_gateway_calls` carries the denials (the data exists).
6. **Truthful refusal, then real revocation** — for a truthful-refusal subject: `SUSPEND_AGENT` → `REFUSED` with the
   process verifiably still live; grant revocation → subsequent calls `403`, target silent. Never the other way round.
7. **I-1 / I-2 derivation** — memory state and A2A handoffs: truthful absences (`NOT_OBSERVE`), not misses to excuse.
8. **Authority** — human delegation chains reconstruct for NATIVE executions; external agents attribute by grant (F-2).
9. **Tenant isolation** — nothing from `contoso-logistics` is reachable, listed or traversable from `northwind-pfg`.
10. **Seal precedence** — `anchor.json` (`created_at 2026-09-27T19:09:19+00:00`, `combined_root e06a0753…`) predates ACT's
    first DT1 execution; the artifacts still hash to the anchor.

## Prerequisites Stage 2 inherits from the programme

O-11 (image embeds `backend/.keys/`) must be closed before any non-lab deployment; V9-1 needs a gate decision or
`statement_timeout`/`temp_file_limit` on the application role; a fresh dedicated lab database (never the shared dev DB);
the V2.1 egress-deny wrapper for any real process; no cloud spend without a signed authorization. Stage 2 may not modify
production ACT to make the twin work.
