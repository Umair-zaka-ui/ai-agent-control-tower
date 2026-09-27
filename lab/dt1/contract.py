"""DT1 Stage 1 - the observability_contract.

What the CURRENT ACT architecture can legitimately OBSERVE / PARTIALLY_OBSERVE /
NOT_OBSERVE / ENFORCE / REFUSE for every class of fact in estate_truth - each
non-OBSERVE entry justified by the actual evidence source or control boundary in
code (file:line taken from the grounding JSON, so the reference is live), never
by "ACT is known to miss this". Stage 2 derives expectations from estate_truth +
this contract; nothing here is a hand-authored expected ACT answer.

The contract is DERIVED: a committed rule set (below) + the grounding JSON +
the estate (for example agent ids). Same inputs => same bytes.
"""
from __future__ import annotations


def _refs(grounding: dict, *specs: tuple[str, str]) -> list[str]:
    """('app/x.py', 'CONST') -> 'app/x.py:<line>' from the AST scan."""
    out = []
    for path, name in specs:
        e = grounding["constants"].get(path, {}).get(name)
        out.append(f"{path}:{e['line']}" if e else f"{path}::{name} (not found at grounding time)")
    return out


def _gap_refs(grounding: dict, gap: str, key: str, limit: int = 4) -> list[str]:
    hits = grounding["gaps"][gap].get(key, [])
    return [f"{h['file']}:{h['line']}" for h in hits[:limit]]


def _agents_with(estate: dict, cond: str, limit: int = 4) -> list[str]:
    return [a["id"] for a in estate["agents"] if cond in a["estate_conditions"]][:limit]


def _agents_where(estate: dict, pred, limit: int = 4) -> list[str]:
    return [a["id"] for a in estate["agents"] if pred(a)][:limit]


def build_contract(estate: dict, grounding: dict, *, contract_version: str) -> dict:
    g = grounding
    status = g["gap_status"]
    E = []

    def entry(fact_class, applies_to, classification, *, evidence_source=None, missing_evidence=None, control_boundary=None,
              precondition=None, gap_id=None, code_refs=(), justification, examples=()):
        if classification != "OBSERVE" and not code_refs:
            raise ValueError(f"{fact_class}: a non-OBSERVE classification needs at least one code reference")
        E.append({"id": f"oc-{len(E) + 1:03d}", "fact_class": fact_class, "applies_to": applies_to, "classification": classification,
                  "evidence_source": evidence_source, "missing_evidence": missing_evidence, "control_boundary": control_boundary,
                  "precondition": precondition, "gap_id": gap_id, "gap_status_at_grounding": status.get(gap_id) if gap_id else None,
                  "code_refs": list(code_refs), "justification": justification, "example_agent_ids": sorted(examples)})

    # ---- existence / inventory -------------------------------------------------------------------------------
    entry("agent.exists", "agents with origin_category=NATIVE (ACT runs them)", "OBSERVE",
          evidence_source="agents table (ACT-created rows; control_state GOVERNED)",
          code_refs=_refs(g, ("app/runtime/registry/control.py", "CONTROL_STATES")),
          justification="A native agent is created through ACT's own registry; its existence is ACT's own record.",
          examples=_agents_where(estate, lambda a: a["origin_category"] == "NATIVE"))
    entry("agent.exists", "external agents listed by a configured HTTP registry discovery source (inventory_status=SHADOW_DISCOVERABLE or REGISTERED_IN_ACT)", "OBSERVE",
          evidence_source="discovery_sources -> HTTP_AGENT_REGISTRY adapter -> discovery_observations -> ReconciliationService CREATE (control_state DISCOVERED)",
          precondition="a DiscoverySource for that registry is configured in the tenant and a sweep runs; the registry is a real service (REAL_EXTERNAL_SERVICE_REQUIRED_STAGE2)",
          code_refs=_refs(g, ("app/discovery/adapters/http_agent_registry.py", "ADAPTER_KEY"), ("app/discovery/reconciliation.py", "LINK_CREATE_CONFIDENCE_THRESHOLD")),
          justification="Discovery is source-driven evidence: the adapter fetches the registry's list, each item becomes an append-only observation, and reconciliation derives a DISCOVERED agent.",
          examples=_agents_with(estate, "REGISTRY_DISCOVERABLE"))
    entry("agent.exists", "external agents listed by the cloud inventory (Bedrock Agents) source", "OBSERVE",
          evidence_source="discovery_sources -> AWS_BEDROCK_AGENTS adapter (ListAgents) -> observations -> reconciliation",
          precondition="a source with a read-only credential is configured; Stage 2 supplies the inventory service (mock or sandbox); the adapter is present only on the validation stack (ADR-0024, unmerged)",
          code_refs=_refs(g, ("app/discovery/adapters/aws_bedrock_agents.py", "ADAPTER_KEY")),
          justification="The V7.5 adapter discovers exactly Bedrock AgentSummary constructs; existence of a listed agent is observable evidence once a source exists.",
          examples=_agents_with(estate, "CLOUD_DISCOVERABLE"))
    entry("agent.exists", "dark shadow agents (inventory_status=SHADOW_DARK: no discovery source lists them)", "NOT_OBSERVE",
          missing_evidence="ACT has no network/process scanning; discovery is strictly source-driven and the fixed adapter registry has exactly two adapters",
          code_refs=_refs(g, ("app/discovery/adapters/http_agent_registry.py", "ADAPTER_KEY"), ("app/discovery/adapters/aws_bedrock_agents.py", "ADAPTER_KEY")),
          justification="An agent that no configured source lists produces no observation; there is no evidence source that could reach it.",
          examples=_agents_with(estate, "SHADOW_DARK"))
    # ---- ownership / lifecycle / provenance -----------------------------------------------------------------
    entry("agent.ownership", "accountable owners of agents known to ACT", "OBSERVE",
          evidence_source="agents.owner_id / owner_type / technical_owner_id / compliance_owner_id (+ posture rule no_accountable_owner for absence)",
          code_refs=_refs(g, ("app/posture/rules.py", "RULES")),
          justification="Ownership is a first-class column set; its absence is itself observable and evaluated by a posture rule.",
          examples=_agents_where(estate, lambda a: a["known_to_act_inventory"]))
    entry("agent.ownership", "the enterprise's actual owner of an agent ACT has not discovered or that was discovered but never claimed", "NOT_OBSERVE",
          missing_evidence="no evidence source carries enterprise ownership for a discovered agent; ownership enters ACT only through claim (AgentControlStateService) or registration",
          code_refs=_refs(g, ("app/runtime/registry/control.py", "CONTROL_STATES")),
          justification="For a DISCOVERED row ACT can state 'unowned in ACT'; it cannot observe who actually operates the process.",
          examples=_agents_with(estate, "SHADOW_DISCOVERABLE"))
    entry("agent.lifecycle", "lifecycle_status of NATIVE agents", "OBSERVE", evidence_source="agents.lifecycle_status (AGENT_LIFECYCLE state machine)",
          code_refs=_refs(g, ("app/runtime/services.py", "AGENT_LIFECYCLE")), justification="ACT owns the lifecycle of the agents it runs.",
          examples=_agents_where(estate, lambda a: a["origin_category"] == "NATIVE"))
    entry("agent.lifecycle", "the enterprise's approval/lifecycle state of an external process", "NOT_OBSERVE",
          missing_evidence="agents.lifecycle_status records ACT's registry state for the row, not the external system's own approval workflow; no ingestion of external approval state exists",
          code_refs=_refs(g, ("app/runtime/services.py", "AGENT_LIFECYCLE")),
          justification="ACT's lifecycle column is ACT's record; nothing reads the external operator's approval state.",
          examples=_agents_where(estate, lambda a: a["origin_category"] != "NATIVE"))
    entry("agent.provenance", "origin_category / origin_provider", "PARTIALLY_OBSERVE",
          evidence_source="agents.origin_category (CHECK NATIVE/EXTERNAL/UNKNOWN) and the soft origin_provider vocabulary; discovered agents carry the adapter's origin_provider",
          precondition="provenance quality beyond 'which adapter reported it' is not modelled; UNKNOWN is the truthful value when no source attests provenance",
          code_refs=_refs(g, ("app/runtime/registry/control.py", "ORIGIN_CATEGORIES"), ("app/runtime/registry/control.py", "ORIGIN_PROVIDERS")),
          justification="Category and provider are observable; the estate's finer 'provenance_quality' (documented/partial/unknown) has no field and collapses to the category.",
          examples=_agents_with(estate, "UNKNOWN_PROVENANCE"))
    # ---- credentials / tools / MCP / resources ---------------------------------------------------------------
    entry("credential.posture", "credentials ACT holds (tool_credentials, provider_credentials, connector_credentials) and agent API keys", "OBSERVE",
          evidence_source="tool_credentials / provider_credentials / connector_credentials rows; posture rules stale_credential, expired_credential_still_active, dormant_agent_with_active_credential",
          code_refs=_refs(g, ("app/posture/rules.py", "RULES")),
          justification="Staleness/expiry of ACT-held credentials is evaluated by deterministic posture rules over ACT's own rows.",
          examples=_agents_where(estate, lambda a: any(True for _ in a["credential_ids"]) and a["known_to_act_inventory"]))
    entry("credential.posture", "credentials held OUTSIDE ACT (shared service accounts, personal tokens used by external or dark processes) and their over-privilege", "NOT_OBSERVE",
          missing_evidence="no inventory of external credentials and no IAM/role ingestion exists; the estate's credential.posture for held_in_act=false has no ACT counterpart",
          code_refs=_refs(g, ("app/posture/rules.py", "RULES"), ("app/discovery/adapters/aws_bedrock_agents.py", "REQUIRED_IAM_ACTIONS")),
          justification="Posture rules read ACT-held credential rows only; the cloud adapter lists agents, not IAM policies (one action, bedrock:ListAgents).",
          examples=_agents_where(estate, lambda a: "SHARED_CREDENTIAL" in a["estate_conditions"] or "OVER_PRIVILEGED_CREDENTIAL" in a["estate_conditions"]))
    entry("tool.approval", "tools registered in ACT and an agent's declared dependency on them", "OBSERVE",
          evidence_source="tools rows + DEPENDS_ON_TOOL edges; posture rules unapproved_tool, excessive_tool_scope, dangerous_dependency",
          code_refs=_refs(g, ("app/models/graph.py", "DEPENDENCY_EDGE_TYPES"), ("app/posture/rules.py", "RULES")),
          justification="Tool approval and scope are ACT records; the dependency edge makes the relationship evaluable.",
          examples=_agents_with(estate, "UNAPPROVED_TOOL"))
    entry("mcp.trust", "MCP servers registered in ACT (via the Tool domain) and DEPENDS_ON_MCP_SERVER edges", "OBSERVE",
          evidence_source="mcp_servers.trust_status (APPROVED/PENDING/REJECTED/UNKNOWN) + edges; posture rule unapproved_mcp_dependency",
          code_refs=_refs(g, ("app/models/graph.py", "MCP_TRUST_STATUSES"), ("app/graph/dependencies.py", "_EDGE_SHAPE")),
          justification="ADR-0018: an MCP server is a first-class row; its trust status and an agent's declared dependency are evaluable.",
          examples=_agents_with(estate, "UNAPPROVED_MCP"))
    entry("mcp.trust", "MCP use by an external process that was never declared or derived as an edge", "NOT_OBSERVE",
          missing_evidence="dependency edges are DECLARED by an operator or DERIVED from ACT's own execution rows (build_for_agent); no runtime MCP traffic of an external process is observed",
          code_refs=_refs(g, ("app/graph/dependencies.py", "_EDGE_SHAPE")),
          justification="Without an edge there is no fact in ACT; the graph never renders an absence as 'no dependency' (unknown != safe), but it cannot see the undeclared one either.",
          examples=_agents_where(estate, lambda a: not a["known_to_act_inventory"] and a["mcp_server_ids"]))
    entry("dependency.path", "agent -> tool/MCP/credential -> resource paths and their blast radius", "PARTIALLY_OBSERVE",
          evidence_source="control_graph_edges (DEPENDENCY_EDGE_TYPES) walked by traverse_with_edges; blast radius returns incomplete=true at the depth cap, never a false 'empty'",
          precondition="every hop must exist as a recorded edge (EXPLICIT/DERIVED/DISCOVERED) between nodes that resolve in the tenant; unrecorded hops are invisible (F5-3: blast radius is only as true as recorded edges)",
          code_refs=_refs(g, ("app/models/graph.py", "DEPENDENCY_EDGE_TYPES"), ("app/graph/traversal.py", "MAX_TRAVERSAL_DEPTH")),
          justification="Reachability is derived from recorded edges only; the estate's sensitive_reachability paths are observable exactly when each hop is an ACT edge.",
          examples=_agents_with(estate, "DANGEROUS_DEPENDENCY_SENSITIVE_REACH"))
    entry("resource.sensitivity", "sensitive resources as graph nodes", "PARTIALLY_OBSERVE",
          evidence_source="resources rows (resource_type free text) as RESOURCE nodes",
          precondition="ACT has no sensitivity classification on resources; 'RESTRICTED/CONFIDENTIAL' in the estate maps to agents.data_classification on the consuming agent, not to the resource",
          code_refs=_refs(g, ("app/models/graph.py", "NODE_TYPES")),
          justification="A resource is observable as a node; its sensitivity is not a resource attribute in ACT.",
          examples=_agents_where(estate, lambda a: a["data_classification"] in ("RESTRICTED", "CONFIDENTIAL")))
    # ---- delegation / A2A / memory ---------------------------------------------------------------------------
    entry("delegation.human", "human -> human delegations", "OBSERVE", evidence_source="delegations rows + DELEGATES_TO edges (create_delegation_edge); _delegation_prefix in authority-chain reconstruction",
          code_refs=_refs(g, ("app/models/graph.py", "EDGE_TYPES")), justification="Human delegation is a recorded row with a producer.",
          examples=_agents_where(estate, lambda a: a["control_group"], 2))
    entry("authority.agent_to_agent", "agent -> agent authority (AGENT_DELEGATES_TO / TRUSTS between agents)", "NOT_OBSERVE",
          missing_evidence="AGENT_DELEGATES_TO is declared in EDGE_TYPES but no code path creates such an edge (no producer, no ingestion); TRUSTS edges exist only when an operator declares them",
          gap_id="I-2", code_refs=_gap_refs(g, "I-2", "references_outside_models") + _refs(g, ("app/models/graph.py", "EDGE_TYPES")),
          justification="The edge type exists so ACT never has to invent it; nothing produces it, so the estate's agent_authority facts have no ACT counterpart until an operator declares them.",
          examples=_agents_with(estate, "I2_RELEVANT"))
    entry("a2a.handoff", "actual runtime agent-to-agent handoffs (LangGraph state edges, CrewAI delegation, HTTP A2A calls)", "NOT_OBSERVE",
          missing_evidence="no A2A protocol or framework-relationship ingestion; the gateway observes an agent's own boundary calls, never which peer caused them",
          gap_id="I-2", code_refs=_gap_refs(g, "I-2", "references_outside_models"),
          justification="V4/V7 measured 22 real handoffs -> 0 observed and 0 inferred; the absence is correct behaviour (no invented edge) and the boundary is the lack of any ingestion path.",
          examples=[h["from_agent_id"] for h in estate["a2a_handoffs"]][:4])
    entry("memory.state", "persistent agent memory/context (what an agent remembers, where, for how long)", "NOT_OBSERVE",
          missing_evidence="no table or model represents runtime memory or context state; the nearest field, agent_definitions.memory_requirements, is a declared requirement on a definition, not observed state",
          gap_id="I-1", code_refs=_gap_refs(g, "I-1", "nearest_related_field_not_a_state_model") or ["app/models/runtime.py"],
          justification="Nothing in ACT reads, stores or evaluates an agent's memory; a memory store that is also a RESOURCE node is observable only as a dependency edge if declared.",
          examples=_agents_with(estate, "I1_RELEVANT"))
    # ---- gateway / detection ---------------------------------------------------------------------------------
    entry("gateway.call", "boundary calls (allowed and denied) by GATEWAY_ENFORCED external agents", "OBSERVE",
          evidence_source="external_gateway_calls (one row per call: authz_decision, outcome, dispatch_status, grant, target)",
          precondition="agent REGISTERED with external_enforcement_mode=GATEWAY_ENFORCED and a grant; the process is a real independent caller (ACTIVE_REAL_PROCESS_REQUIRED_STAGE2)",
          code_refs=_gap_refs(g, "F6-1", "gateway_records_written_at") + _refs(g, ("app/models/bridge.py", "STORABLE_ENFORCEMENT_MODES")),
          justification="Every signed call is recorded before dispatch; denial and allowance are both evidence.",
          examples=_agents_with(estate, "GATEWAY_ENFORCED_EXTERNAL"))
    entry("gateway.scope", "a call outside the grant's scope", "ENFORCE",
          control_boundary="GatewayService.decide: identity.scoped_for(capability, target) -> DENY 'outside grant scope'; denied calls are never dispatched (DB CHECK ck_ext_calls_denied_never_dispatched)",
          precondition="same as gateway.call",
          code_refs=_gap_refs(g, "F6-1", "gateway_records_written_at"),
          justification="Scope bounds but never grants; the denial is a real effect (no dispatch), verified in V4/V6/V7.",
          examples=_agents_with(estate, "OUT_OF_SCOPE_GATEWAY_ATTEMPTS"))
    entry("detection.gateway_denials", "a threat finding for repeated denied boundary calls by a gateway-enforced agent", "NOT_OBSERVE",
          missing_evidence="all six threat rules read agent_executions / runtime_governance_decisions / tool_calls; none reads external_gateway_calls, and a gateway-enforced agent never produces an execution",
          gap_id="F6-1", code_refs=_gap_refs(g, "F6-1", "threat_rules_reading_execution_tables", 6),
          justification="Enforcement is perfect and detection is silent for this agent class - a wiring gap (the data exists in external_gateway_calls), confirmed in V6 and felt in V7 (39 denials -> 0 findings).",
          examples=_agents_with(estate, "F6_1_RELEVANT"))
    entry("detection.native_denials", "a threat finding for repeated governance denials of a NATIVE agent", "OBSERVE",
          evidence_source="threat rule governance_denial_spike over runtime_governance_decisions joined to agent_executions (threshold min_denials=3)",
          code_refs=_gap_refs(g, "F6-1", "threat_rules_reading_execution_tables", 3),
          justification="For ACT-run agents the execution rows exist and the rule fires deterministically.",
          examples=_agents_where(estate, lambda a: a["origin_category"] == "NATIVE" and a["lifecycle_status"] == "ACTIVE", 3))
    entry("gateway.shared_grant", "an undiscovered process calling the gateway with a grant issued to another registered agent", "PARTIALLY_OBSERVE",
          evidence_source="external_gateway_calls attribute the call to the grant's agent (key_id -> grant -> agent_id)",
          precondition="ACT cannot distinguish the true caller from the grant's registered agent; the attribution is to the grant holder",
          code_refs=_gap_refs(g, "F6-1", "gateway_records_written_at"),
          justification="The call is observed and enforced, but attributed to the wrong (registered) agent - a credential-sharing fact the estate records objectively.",
          examples=_agents_with(estate, "SHARED_GATEWAY_GRANT"))
    # ---- control / containment / authority ------------------------------------------------------------------
    entry("control.suspend_external_process", "suspending or terminating an external/discovered agent's process", "REFUSE",
          control_boundary="ContainmentOrchestrator.truthful_capability: performs only when control_state == 'GOVERNED'; every other agent gets status REFUSED with a refusal_reason and no effect (ADR-0020); GOVERNED is legal only for NATIVE (ADR-0023)",
          code_refs=_refs(g, ("app/threat/containment.py", "_REVERSIBLE"), ("app/runtime/registry/control.py", "LEGAL_CONTROL_STATES_BY_ORIGIN")),
          justification="ACT does not run the process, so it cannot truthfully claim to stop it; the refusal is the correct, verified behaviour (V6: REFUSED, agent still live).",
          examples=estate["truthful_refusal_subject_agent_ids"][:4])
    entry("control.revoke_grant", "revoking an external agent's gateway grant", "ENFORCE",
          control_boundary="ExternalGrantService.revoke sets revoked_at; ExternalGrantService.verify then rejects the key (EXTERNAL_GRANT_REVOKED, 403); revocation is uncached",
          precondition="the agent holds a grant ACT issued",
          code_refs=_refs(g, ("app/models/bridge.py", "STORABLE_ENFORCEMENT_MODES")),
          justification="This is authority ACT genuinely controls; V6/V7 verified the effect (subsequent calls 403, target silent).",
          examples=estate["truthful_refusal_subject_agent_ids"][:4])
    entry("control.suspend_native", "suspending a NATIVE GOVERNED agent", "ENFORCE",
          control_boundary="containment SUSPEND_AGENT -> KillSwitchService (lifecycle_status SUSPENDED, active executions cancelled); requires explicit confirmation; not reversible by automation",
          code_refs=_refs(g, ("app/threat/containment.py", "_REVERSIBLE")),
          justification="ACT runs the agent, so the effect is real and effect-verified (V6).",
          examples=_agents_where(estate, lambda a: a["origin_category"] == "NATIVE" and a["control_group"], 3))
    entry("control.govern_external", "declaring an EXTERNAL/UNKNOWN agent GOVERNED", "REFUSE",
          control_boundary="AgentControlStateService: GOVERNED requires origin NATIVE (CONTROL_STATE_ORIGIN_INCOMPATIBLE, 409)",
          code_refs=_refs(g, ("app/runtime/registry/control.py", "LEGAL_CONTROL_STATES_BY_ORIGIN")),
          justification="The column cannot lie in either direction; an external agent tops out at REGISTERED.",
          examples=_agents_where(estate, lambda a: a["origin_category"] != "NATIVE" and a["known_to_act_inventory"], 3))
    entry("reconciliation.native_collision", "a discovered identifier equal to a NATIVE agent's external_reference", "OBSERVE",
          evidence_source="ReconciliationService: NATIVE collision always FLAGs a discovery_findings row (RECONCILIATION_AMBIGUOUS); never a silent merge",
          code_refs=_refs(g, ("app/models/discovery.py", "FINDING_TYPES")),
          justification="The conflict is surfaced as a human-review finding, deterministically.",
          examples=[c["native_agent_id"] for c in estate["identifier_collisions"]])
    entry("reconciliation.staleness", "a discovered agent that disappears from its source", "PARTIALLY_OBSERVE",
          evidence_source="check_staleness -> STALE_AGENT finding, never a deletion; auto-resolved on re-observation",
          precondition="the sweep that misses it must be complete; a bounded/partial sweep evaluates staleness against a partial set (V9-5) and can flag agents that still exist",
          code_refs=_refs(g, ("app/models/discovery.py", "FINDING_TYPES"), ("app/models/discovery.py", "RUN_STATUSES")),
          justification="Staleness is observable and non-destructive; its precision depends on the sweep being complete.",
          examples=_agents_with(estate, "REGISTRY_DISCOVERABLE", 3))
    entry("graph.reachability_depth", "reachability over branching trust/delegation graphs at depth >= 16", "PARTIALLY_OBSERVE",
          evidence_source="AuthorityChainService.reachability over control_graph_edges with a path-array cycle guard",
          precondition="the CTE enumerates simple paths, so cost is exponential in branching x depth; shallow or tree-like graphs answer, dense ones abort at the default depth (V9-1)",
          gap_id="V9-1", code_refs=_gap_refs(g, "V9-1", "path_array_guard"),
          justification="The answer exists relationally (a frontier-dedup form returns it), but the shipped query shape cannot complete on dense graphs.",
          examples=_agents_with(estate, "I2_RELEVANT", 2))
    entry("authority.chain_external", "an authority chain for an action by an external agent", "NOT_OBSERVE",
          missing_evidence="reconstruct_authority_chain starts FROM agent_executions; gateway-enforced external agents produce none - their actions are attributed by grant and issuer, not by a reconstructed chain",
          gap_id="F-2", code_refs=_gap_refs(g, "F-2", "reconstruct_reads_executions"),
          justification="Attribution exists (grant -> agent -> issuer), but the 5.3 chain surface does not cover it.",
          examples=_agents_with(estate, "GATEWAY_ENFORCED_EXTERNAL", 3))
    entry("tenant.isolation", "any relationship, traversal or read across tenants", "ENFORCE",
          control_boundary="organization_id on every domain table; per-hop organization_id predicate in every recursive CTE; cross-tenant nodes resolve to nothing (404-class refusal, no existence leak)",
          code_refs=_refs(g, ("app/graph/traversal.py", "MAX_TRAVERSAL_DEPTH")),
          justification="Verified at every rung in V5 and V9: hostile cross-tenant edges are truncated at the tenant edge.",
          examples=[a["id"] for a in estate["agents"] if a["tenant_id"] == next(t["id"] for t in estate["tenants"] if t["role"] == "ISOLATION_CONTROL")][:2])
    entry("posture.control_group", "well-governed agents (the control group)", "OBSERVE",
          evidence_source="the 16 posture rules evaluate every agent; a healthy agent should produce no serious finding",
          code_refs=_refs(g, ("app/posture/rules.py", "RULES")),
          justification="Observability includes the absence of findings; Stage 2 measures specificity/false positives here.",
          examples=estate["control_group_agent_ids"][:4])

    by_class: dict[str, int] = {}
    for e in E:
        by_class[e["classification"]] = by_class.get(e["classification"], 0) + 1
    return {
        "contract_version": contract_version,
        "generator": estate["generator"],
        "classes": ["OBSERVE", "PARTIALLY_OBSERVE", "NOT_OBSERVE", "ENFORCE", "REFUSE"],
        "gap_status_at_grounding": status,
        "derivation_rule": ("Stage 2 derives an expectation per estate fact: a fact whose class is OBSERVE (all hops OBSERVE for a path) "
                            "should appear in ACT's answer; a fact with any NOT_OBSERVE hop yields a truthful absence to be verified as such; "
                            "PARTIALLY_OBSERVE applies its precondition; ENFORCE/REFUSE are effect-verified. No entry here is an expected ACT output."),
        "entries": E,
        "summary": {"entries": len(E), "by_class": dict(sorted(by_class.items())),
                    "entries_with_gap_id": sorted({e["gap_id"] for e in E if e["gap_id"]})},
    }
