# ACT_THREAT_COVERAGE_MATRIX — v1.0 (2026-09-18)

Repository truth verified at `validation/v1-threat-intel` = `2b4f57b` (V0 PASSED baseline). Register rows
refer to `AI_SECURITY_RESEARCH_REGISTER.csv`. **The master plan's §H coverage map is not in this
repository**, so the threat domains T1–T25 below are V1's reconstruction from the retrieved sources
(OWASP ASI01–10 and LLM01–10, MCP spec attacks, ATLAS, A2A, identity research, incidents, threats-from-AI)
and every capability claim was checked against live code, not against the plan.

`coverage_status` ∈ COVERED (proven) · COVERED (unproven — test planned) · PARTIAL · NOT COVERED ·
NOT APPLICABLE · NOT OBSERVABLE BY DESIGN. "Proven" means a named test exists at `2b4f57b` and passed in
the V0.2 final run (2,648 passed).

| threat_id | domain | register_row(s) | ACT_capability (live service/authority) | existing_proof | red_team_test_planned | coverage_status |
|---|---|---|---|---|---|---|
| T1 | Direct/indirect prompt injection hijacking an ACT-run agent's actions | R-001 R-006 R-033 R-070 R-071 | 4.3 `GovernancePolicyService`/engine (deny/approve per action) and M1 `egress_guard` bound *what* an action can do; **no content-level injection detection** — `app/threat/rules.py` records the evidence gap | `test_ac07_active_kill_switch_is_always_a_block`, `test_ac03_require_approval_creates_a_real_enforced_governance_policy` (bounding); NONE for detection | V4-PI-01..05 | PARTIAL |
| T2 | Agent goal hijack / plan manipulation (ASI01) | R-004 R-005 | Same bounding controls as T1; no plan/goal representation in ACT | NONE | V4-GH-01 | PARTIAL |
| T3 | Tool misuse & excessive agency (ASI02, LLM06, T0053) | R-002 R-007 R-047 | 4.3 tool policies + `REQUIRE_APPROVAL`; 5.5 `excessive_tool_scope`, `unapproved_tool`; 5.6 `repeated_tool_egress_denial`, `tool_schema_validation_failure`, `unapproved_mcp_tool_invoked`; 5.7 grant scopes narrow only | `tests/threat` AC-02/AC-03 rules, `tests/posture` rule tests, bridge `test_ac06_an_undeclared_capability_is_refused`, `test_ac07_denies_out_of_scope_call_and_says_what_it_cannot_reach` | V4-TM-01..03 | COVERED (proven) for ACT-run and gateway-routed calls |
| T4 | Unexpected code execution by agents (ASI05; CrewAI/Flowise/MCP STDIO CVEs) | R-015 R-028 R-029 R-059 | ACT executes only its native runtime (M1 executor; no arbitrary code tool). For discovered agents: 5.5 `dangerous_dependency` posture evidence | M1 executor tests; `tests/posture` dangerous_dependency | V7-FW-01, V8-SC-02 | NOT APPLICABLE (native) / PARTIAL (external: evidence only) |
| T5 | Egress / SSRF / data exfiltration via tools (MCP SSRF; NVIDIA default-deny) | R-020 R-051 R-033 | M1 `app/runtime/tools/egress_guard.py` (`EgressPolicy`, `TOOL_EGRESS_DENIED`); 5.6 `repeated_tool_egress_denial` | `tests/runtime` egress-guard tests; `tests/threat` AC-02 | V4-TM-03, V3-MCP-04 | COVERED (proven) for ACT-run tools; default-deny stance to be re-verified in V4 |
| T6 | Identity & privilege abuse of agents (ASI03; Double Agents; NHI vacuum) | R-012 R-035 R-046 R-048 R-055 R-056 | 5.1 canonical agents with accountable owner; M4 machine identity; 4.3 ABAC (`test_subject_attributes_cannot_be_spoofed`); 5.5 `no_accountable_owner`, `unowned_with_production_access`; 5.7 `AuthorizationGateway.authorize_agent` with `identity_kind=AGENT` | `tests/authorization/test_abac.py`, `tests/runtime/test_agent_asset_model.py` (ownership, V0.2 origin×control invariant), bridge `test_ac03_native_mode_routes_to_the_real_4_3_engine_and_kill_switch` | V5-ID-01..07 | COVERED (proven) within ACT's tenancy; cloud service-agent privilege (R-035) NOT OBSERVABLE without I-4 adapters |
| T7 | Credential lifecycle: stale/expired/leaked agent credentials; AI API keys as loot | R-041 R-056 | 5.5 `stale_credential`, `expired_credential_still_active`, `dormant_agent_with_active_credential`; 5.6 `flagged_credential_used`; 5.6 `ISOLATE_CREDENTIAL`; M4.11 credential crypto | `tests/posture` AC-06 rule set; `tests/threat` AC-02/AC-03; `test_key_material_integrity.py` | V5-ID-07, V9-FA-03 | COVERED (proven) |
| T8 | Agentic supply chain: malicious/poisoned tools, skills, packages (ASI04, LLM03, T0010/T0109) | R-009 R-027 R-029 R-058 R-059 | 5.4 `mcp_servers.trust_status` + tool linkage; 5.5 `unapproved_mcp_dependency`, `dangerous_dependency`, `prohibited_model`; 5.9 `ACT.SUPPLY_CHAIN.MCP_TRUST` evidence | `tests/graph/test_dependency_graph.py`, `tests/posture`, `tests/assurance` | V8-SC-01..03 | PARTIAL — trust is a declared status; no integrity verification (hash/pin) of tool descriptions or server code |
| T9 | MCP tool poisoning / rug pull / cross-server shadowing | R-027 R-028 R-032 R-068 | 5.4 records MCP servers and tools as inventory; **no capture of tool descriptions, no hash pinning, no change detection** | NONE | V3-MCP-09, V3-MCP-10, V3-MCP-14 | NOT COVERED |
| T10 | MCP authorization misuse: token passthrough, confused deputy, session hijack, scope inflation | R-018 R-019 R-021 R-023 R-024 R-036 | ACT is neither an MCP server nor an MCP client (no OAuth-proxy role). 5.7 boundary uses signed requests (HMAC, nonce, 300 s window, `(grant_id,nonce)` unique), never bearer tokens; scopes narrow only | bridge `test_ac10_a_replayed_request_is_refused`, `test_ac10_a_stale_signature_is_refused`, `test_ac14_duplicate_nonce_inserts_cannot_both_commit`, `test_ac03_observed_agent_cannot_be_given_a_boundary_credential` | V3-MCP-02..08, V3-MCP-13 | NOT APPLICABLE (MCP OAuth) / COVERED (proven) for the analogous ACT boundary |
| T11 | Memory & context poisoning; RAG poisoning (ASI06, T0070) | R-008 R-005 | **NONE** — no memory, vector or retrieval surface exists in `app/` (I-1 confirmed by grep) | NONE | V4-MP-01 | NOT COVERED (and NOT OBSERVABLE BY DESIGN for agents ACT does not run) |
| T12 | Insecure inter-agent communication / A2A impersonation, card tampering, replay (ASI07, A2A spec) | R-026 R-060 R-061 | 5.3 authority graph has `AGENT_DELEGATES_TO` **declared with no producer** (`app/models/graph.py:68-82`, `test_ac04_graph_never_writes_delegations_and_has_no_agent_delegation_producer`); no A2A ingestion | `tests/graph/test_control_graph.py::test_ac04_*` (proves the absence, not coverage) | V6-A2A-01..03 | NOT OBSERVABLE BY DESIGN (I-2 confirmed) |
| T13 | Cascading failures across agents (ASI08) | R-005 R-044 | 5.4 blast-radius traversal (agents-reaching, recursive CTE); 5.6 rules are per-agent windows; **no cross-agent correlation** | `tests/graph/test_dependency_graph.py` blast radius; milestone `test_ac09` scale | V6-A2A-01 | PARTIAL |
| T14 | Human–agent trust exploitation; approval fatigue/flooding; misleading approval text (ASI09) | R-005 R-040 R-042 R-059 | Approvals exist (M1 approvals, 4.3 `REQUIRE_APPROVAL`, 5.6 `REQUIRE_APPROVAL` containment); **no rate/flood/dedup control and no approval-text integrity control** (grep: none) | `test_ac05_challenge_raises_an_approval_through_the_existing_funnel`, `test_ac08_promotion_into_production_requires_approval` (funnel works) | V10-HA-01..02 | PARTIAL (I-7 confirmed: fatigue/flooding not covered) |
| T15 | Rogue / drifting agents ignoring stop (ASI10; OpenClaw inbox deletion; Hugging Face swarm) | R-043 R-044 R-059 | Kill switch (EXECUTION/AGENT/PROJECT/PLATFORM scopes) dominates everything for ACT-run agents; 5.6 truthful REFUSED for agents ACT does not run; 5.7 grant revocation | `test_ac07_active_kill_switch_is_always_a_block`, `test_ac09_a_kill_during_evaluation_dominates_every_other_decision`, `test_ac06_kill_dominates_a_concurrent_containment_recommendation`, milestone E2E (kill REFUSED, revocation effective) | V9-FA-04 | COVERED (proven) for native; truthfully NOT COVERED for external (by design, ADR-0020/0021/0023) |
| T16 | Shadow / unsanctioned agents and agent sprawl (Agent 365 "sprawl"; HiddenLayer shadow AI) | R-045 R-058 | 5.2 discovery + reconciliation (evidence, no silent merge); 5.5 shadow as derived finding; 5.1 `DISCOVERED` state | `tests/discovery`, `tests/posture` shadow tests, milestone E2E step 1–4 | V8-SC-03 | COVERED (proven) for sources with an adapter — only the HTTP registry adapter exists (I-4) |
| T17 | Cloud/SaaS agent platforms outside ACT's view (Vertex, Bedrock, Copilot Studio, Agentforce, Joule) | R-035 R-045 R-047 R-049 R-061 R-062 | 5.2 adapter seam (`DiscoveryAdapter` ABC, registry) with one implementation | milestone E2E (HTTP registry) | V8-SC-03 | NOT COVERED (I-4 confirmed) |
| T18 | Tenant isolation / cross-tenant existence leakage via agents | (ACT invariant) | `get_or_404` convention everywhere; 5.7 tenant-scoped grants; V0 verified 112–113 tenant tests | V0/V0.2 tenant selection (113 passed) | (regression, every phase) | COVERED (proven) |
| T19 | Over-claimed enforcement (declaring control ACT lacks) | ADR-0020/0021/0023 | 5.6 `truthful_capability`; 5.7 non-storable `NATIVE_ENFORCED`; V0.2 `GOVERNED ⇔ NATIVE` | `test_ac05_observed_agent_containment_is_truthfully_refused[*]`, `test_v02_*`, `test_m51_end_to_end_proof` | (regression) | COVERED (proven) |
| T20 | External gateway boundary abuse: replay, stale signature, undeclared capability, expired grant | R-021 R-023 | 5.7 `CapabilityBoundary`, `ExternalGrantService` | bridge AC-06/AC-07/AC-10/AC-14 (53 tests) | V3-MCP-13 | COVERED (proven) |
| T21 | Connector-level failure attribution (which connector/tool caused an outcome) | R-072 | Deferred by the runtime-never-knows boundary (integration plane keeps execution ignorant of connector internals); no attribution field in `app/integration` | NONE | V7/V8 | NOT OBSERVABLE BY DESIGN (I-3 confirmed) |
| T22 | AI-enabled adversary speed: breakout in minutes, exfil in minutes | R-052 R-044 | Kill-switch latency; 5.6 detection windows; M4.4 cost/behaviour anomalies | `tests/threat` timing not asserted | V9-FA-06 | COVERED (unproven — test planned) |
| T23 | Threats FROM AI: AI-assisted phishing, fraud, social engineering, deepfakes (T0052, T0088, IBM) | R-010 R-057 | ACT governs what its *own* agents may send/do (4.3 action policies, egress allowlists, approvals); it does not inspect third-party inbound content | 4.3 action-decision tests | V9-FA-01 (canary: an ACT-run agent attempting an outbound message/transaction outside policy is denied and audited) | PARTIAL |
| T24 | Threats FROM AI: automated recon, exploit generation, credential abuse, mass automation (Anthropic GTGs, Talos UAT-10147, Mexico breach) | R-034 R-041 R-053 R-059 | Same as T23 plus 5.6 `behavioral_anomaly`, `governance_denial_spike`; kill switch | `tests/threat` AC-02 rules | V9-FA-02, V9-FA-03, V9-FA-07 (canary: synthetic anomalous action bursts trigger detection and containment without any offensive capability) | PARTIAL |
| T25 | Threats FROM AI: autonomous propagation / self-replicating prompts / agent swarms (T0061, HF swarm) | R-006 R-043 R-044 | Kill switch PLATFORM scope; no cross-agent propagation detection | `test_kill_switch_platform_scope_reaches_other_organizations` | V9-FA-04, V9-FA-05 | PARTIAL |

## Summary by coverage_status

| status | count | threat_ids |
|---|---|---|
| COVERED (proven) | 8 | T3, T5, T6, T7, T15 (native), T18, T19, T20 |
| COVERED (unproven — test planned) | 1 | T22 |
| PARTIAL | 8 | T1, T2, T8, T13, T14, T23, T24, T25 |
| NOT COVERED | 3 | T9, T11, T17 |
| NOT APPLICABLE | 2 | T4 (native half), T10 (MCP OAuth half) |
| NOT OBSERVABLE BY DESIGN | 3 | T12, T21, (T11 external half) |

Rows with split status (T4, T10, T11, T15, T16) are counted once under their primary status above.

## Divergences from the master plan's §H hypothesis (as restated in the V1 prompt)

The prompt named five expected gaps; all five **confirmed** against live code (T11/I-1, T12/I-2, T21/I-3,
T17/I-4, T14/I-7). Two claims that would commonly be *assumed* for a platform with "runtime threat
detection" did **not** survive inspection and are recorded as divergences:

- **D-1 — "5.6 detects prompt injection."** It does not. `app/threat/rules.py` ships six rules
  (`behavioral_anomaly`, `governance_denial_spike`, `repeated_tool_egress_denial`,
  `tool_schema_validation_failure`, `unapproved_mcp_tool_invoked`, `flagged_credential_used`) and an
  explicit evidence-gap note that prompt/indirect-injection and delegation-abuse rules are *not*
  delivered for lack of a deterministic signal. Coverage of T1/T2 is bounding (what an action may do),
  not detection.
- **D-2 — "5.4 governs MCP tools."** 5.4 *inventories* MCP servers and tools and derives trust
  evidence; it does not capture tool descriptions, pin versions, or detect post-approval changes (T9).
  The MCP research base (R-027, R-028, R-068) treats those as the primary MCP controls.
