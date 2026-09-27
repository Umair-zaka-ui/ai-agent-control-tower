# DT1 Stage 1 — Estate design (the canonical estate, its truth, and what it is not)

**What DT1 is.** A synthetic, deterministic, hash-sealed enterprise AI-agent estate — the *Digital Twin* — that later
stages point ACT at to measure what ACT truthfully observes, misses, enforces and refuses. **Stage 1 builds the estate
and records its objective truth; it never runs ACT against it.** Code: [`lab/dt1/`](../../lab/dt1/); artifacts:
[`lab/dt1/artifacts/`](../../lab/dt1/artifacts/); this directory holds the records.

**Location decision (§3 of the approved prompt).** Lab code lives under `lab/dt1/` because every post-M5 lab lives under
`lab/<phase>/` (`lab/harness/`, `lab/scale/`, `lab/wrapper/`) and never under `backend/app`; records live under
`docs/dt1/` because the repository keeps programme-level records in their own `docs/<programme>/` directory
(`docs/milestone-5/`, `docs/validation/`), and DT1 is a new programme rather than a validation gate. DT1 tests live in
`lab/dt1/tests/` and run by explicit path with the backend venv's pytest, so the production suite (`backend/tests`,
2,681 + 1 deselected on this stack) is untouched and no file-reading guard is affected.

## The fictional enterprise

**Primary tenant — Northwind Payroll & Finance Group** (`northwind-pfg`): 17 people (business, technical, compliance
and security owners; an analyst, an intern, a contractor), 17 resources, 21 credentials, 21 tools, 7 MCP servers,
2 discovery sources, **56 canonical agents**. **Isolation-control tenant — Contoso Logistics** (`contoso-logistics`):
2 people, 2 resources, 2 credentials, 2 tools, 1 discovery source, **4 canonical agents**. Nothing in one tenant references
anything in the other (the validator enforces it). **Total: 60 canonical agents**, all names fictional, all emails
`@<tenant>.example`, every credential an opaque label with `secret_value = null`.

**Sensitive resources are generic and fictional, never PHI:** Employee Payroll Database (RESTRICTED), Employee Compensation
Records (RESTRICTED), Treasury Payments Queue (RESTRICTED), Financial Records, General Ledger Export, Benefits Enrollment
Store, Audit Log Archive, Copilot Conversation Store, Applicant Tracking System (CONFIDENTIAL), plus INTERNAL and PUBLIC
resources. Healthcare is a possible future vertical, deliberately not this estate.

## Canonical agents with overlapping properties — not cohorts

Each agent is one entity carrying many properties at once. The brief's own example is in the estate:

| Finance Research Assistant (`agt-…`) | value |
|---|---|
| origin / provider | EXTERNAL / CUSTOM |
| inventory | **SHADOW_DISCOVERABLE** — exists and is listed by the enterprise registry, unclaimed, not in ACT's inventory |
| owners | none (business / technical / compliance all unknown) |
| credential | `svc-finance-shared` — **SHARED + OVER_PRIVILEGED**, reaches payroll, compensation, financial records, ledger, treasury queue |
| MCP | `finance-mcp-legacy` — trust **UNKNOWN**, provenance DISCOVERED |
| sensitive reach | Employee Payroll Database (RESTRICTED) via the shared credential and the legacy MCP |
| gateway relationship | calls ACT's gateway **with a grant issued to another agent** (`Finance Data Connector`) and attempts targets outside that grant's scope |
| memory | PERSISTENT in the Copilot Conversation Store, 365 days |
| reality | ACTIVE_REAL_PROCESS_REQUIRED_STAGE2 |
| estate conditions | OVER_PRIVILEGED_CREDENTIAL, SHARED_CREDENTIAL, UNOWNED, PRODUCTION_ACCESS_UNOWNED, SHADOW_DISCOVERABLE, UNKNOWN_PROVENANCE, UNAPPROVED_MCP, DANGEROUS_DEPENDENCY_SENSITIVE_REACH, OUT_OF_SCOPE_GATEWAY_ATTEMPTS, SHARED_GATEWAY_GRANT, F6_1_RELEVANT, I1_RELEVANT, I2_RELEVANT, TRUTHFUL_REFUSAL_SUBJECT, REGISTRY_DISCOVERABLE |

**Property dimensions**, each mapped to a real ACT field where one exists (`SCHEMA_GROUNDING.md`) or recorded as an
*objective estate-only attribute* where ACT has none — which is itself a fact the observability contract uses:

| dimension | estate field | ACT counterpart (grounded) |
|---|---|---|
| origin / provenance | `origin_category`, `origin_provider`, `provenance_quality` | `agents.origin_category` (CHECK), `agents.origin_provider`; provenance *quality* has no field |
| control / inventory | `control_state`, `inventory_status`, `known_to_act_inventory`, `discoverable_via_source_ids` | `agents.control_state` (legal per origin, ADR-0023); shadow is not a column — it is "no row / DISCOVERED and unclaimed" |
| ownership | `owners.{business,technical,compliance}_person_id`, `owner_type` | `agents.owner_id/owner_type/technical_owner_id/compliance_owner_id` |
| lifecycle / approval | `lifecycle_status` | `agents.lifecycle_status` (`AGENT_LIFECYCLE`) — ACT's record, not the enterprise's approval workflow |
| identity | `identities[]` (AGENT_IDENTITY / SERVICE_ACCOUNT / EXTERNAL_CLIENT) | `agent_identities`, `service_accounts`, `external_clients` |
| credential posture | `credentials[].posture`, `held_in_act`, `last_used_days_ago`, `expired_days_ago` | `tool_credentials` / `provider_credentials` / `connector_credentials` for ACT-held ones; none for external credentials |
| tools / MCP | `tools[].approval_state`, `mcp_servers[].trust_status` + `DEPENDS_ON_*` edges | `tools`, `mcp_servers.trust_status`, `control_graph_edges` (`_EDGE_SHAPE`) |
| resource reach | `sensitive_reachability[]` (objective BFS over the estate's own edges) | `traverse_with_edges` over recorded edges; resource sensitivity has no field |
| delegation | `delegations[]` human→human; `agent_authority[]` agent→agent | `delegations` + `DELEGATES_TO` edges; `AGENT_DELEGATES_TO` declared, **no producer** (I-2) |
| actual A2A | `a2a_handoffs[]` | none (I-2) |
| actual memory | `memory.{kind,store_resource_id,retention_days}` | none (I-1) |
| gateway | `gateway.{external_enforcement_mode, grants[], attempted_targets_*, uses_grant_issued_to_agent_id}` | `agents.external_enforcement_mode`, `external_capability_grants`, `external_gateway_calls` |
| environment / criticality / classification / autonomy | as named | `agents.default_environment / criticality / data_classification / autonomy_level` (schema patterns) |
| reality | `reality_class` | none — a Stage-2 instruction |

**Estate conditions are derived from facts** (`estate.derive_conditions`), never typed per agent, so they remain
objective classifications of what exists. Serious conditions (credential posture, ownership, shadow status, provenance,
approval, dangerous reach, dormancy, collision, out-of-scope gateway attempts, shared grants) are distinguished from
structural ones (gateway-enforced, truthful-refusal subject, I-1/I-2/F6-1 relevance, discoverability).

## Distribution (seed `dt1-canonical-v2-2026`)

| | count |
|---|---|
| canonical agents | **60** (56 primary + 4 isolation-control) |
| healthy control group | **12** — full ownership, ACTIVE, approved tools/MCP, least-privilege credentials, zero serious conditions |
| origin | NATIVE 23 · EXTERNAL 32 · UNKNOWN 5 |
| control state | GOVERNED 23 (all NATIVE) · REGISTERED 15 · CLAIMED 5 · DISCOVERED 17 |
| inventory | REGISTERED_IN_ACT 43 · SHADOW_DISCOVERABLE 12 · SHADOW_DARK 5 |
| enforcement mode (external, known to ACT) | GATEWAY_ENFORCED 12 · ADVISORY 2 · OBSERVED 4 |
| lifecycle | ACTIVE 56 · SUSPENDED 1 · RETIRED 1 · DRAFT 1 · PENDING_APPROVAL 1 |
| reality | ACTIVE_REAL_PROCESS_REQUIRED_STAGE2 15 · REAL_EXTERNAL_SERVICE_REQUIRED_STAGE2 9 · SIMULATED_ASSET 33 · DORMANT_ASSET 3 |
| conditions (agents carrying each) | UNOWNED 18 · OVER_PRIVILEGED_CREDENTIAL 16 · PRODUCTION_ACCESS_UNOWNED 15 · SHADOW_DISCOVERABLE 12 · UNKNOWN_PROVENANCE 11 · UNAPPROVED_MCP 10 · SHARED_CREDENTIAL 7 · F6_1_RELEVANT 6 · I1_RELEVANT 6 · UNAPPROVED_TOOL 6 · SHADOW_DARK 5 · DANGEROUS_DEPENDENCY_SENSITIVE_REACH 12 · DORMANT_WITH_ACTIVE_CREDENTIAL 3 · NATIVE_REFERENCE_COLLISION 2 · STALE_CREDENTIAL 2 · EXPIRED_CREDENTIAL_STILL_ACTIVE 1 · SHARED_GATEWAY_GRANT 1 |
| structural | I2_RELEVANT 12 · TRUTHFUL_REFUSAL_SUBJECT 13 · GATEWAY_ENFORCED_EXTERNAL 12 · REGISTRY_DISCOVERABLE 26 (25 enterprise + 1 Contoso) · CLOUD_DISCOVERABLE 6 |
| overlap | 27 agents carry 2+ serious conditions · 19 carry 4+ · 38 identities (35 + 3) |
| relationships | 244 dependency edges · 4 human delegations · 5 agent-authority facts · 6 real A2A handoffs (all crossing a process boundary) · 78 sensitive-reach paths · 1 identifier collision |

The full per-agent table is [`AGENT_PROPERTY_MATRIX.md`](AGENT_PROPERTY_MATRIX.md).

## The adversarial conditions, as objective facts

- **F6-1-relevant (6 agents):** external, GATEWAY_ENFORCED, REGISTERED processes that attempt targets outside their grant
  (e.g. the Finance Close Orchestrator attempting `treasury-initiate-payment`), plus the shared-grant shadow. Their
  enforcement will happen at the gateway; no execution row ever exists for them. The estate records the *behaviour*;
  whether a finding appears is Stage 2's derivation.
- **I-1-relevant (6):** agents with persistent memory in a real store (Copilot Conversation Store) or on a desktop.
- **I-2-relevant (12):** six real handoffs across LangGraph state edges, CrewAI task delegation and HTTP A2A calls, and
  five agent→agent authority facts.
- Over-privileged / shared / stale / expired credentials; unknown provenance; legacy and rejected MCP servers; unapproved
  tools (`treasury-initiate-payment`, `code-exec`, `file-fetch`); unowned production access; dormant agents holding
  active credentials; a NATIVE agent (`Vendor Master Sync`) whose `external_reference` equals a discoverable external
  process's identifier (`vendor-master-sync`) — the no-silent-merge condition.
- **Truthful-refusal subjects (13):** external processes ACT does not run but for which ACT holds a grant it can revoke —
  e.g. the Vendor Portal Sync Bot (vendor-operated), the Treasury Payment Scheduler, and the Finance Close Orchestrator.

## Reality classification — what Stage 2 must instantiate

`ACTIVE_REAL_PROCESS_REQUIRED_STAGE2` (15): every gateway-enforced or shared-grant agent and every A2A participant must run
as a genuine independent process in Stage 2. `REAL_EXTERNAL_SERVICE_REQUIRED_STAGE2` (9): agents that exist only through a
discovery source — the **Enterprise Agent Registry (HTTP)** and the **Cloud Agent Inventory (Bedrock, us-east-1)** must
be real services on a real socket; the registry path is the guaranteed **process/network-boundary crossing**. `SIMULATED_ASSET`
(33): NATIVE agents ACT will create through its own API and dark shadows that only exist in truth. `DORMANT_ASSET` (3).
Stage 1 instantiates none of them.

## What the estate deliberately does not contain

No ACT expectations (`EXPECTED_*`, findings, verdicts — the validator rejects the keys), no PHI, no real person, no secret
value, no cross-tenant relationship, no ACT execution artifact. F6-1 is an estate condition and a documented limitation
(`LIMITATIONS.md`), not a demo hero.
