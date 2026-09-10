# Security posture rules (Phase 5.5 / M5.5)

The deterministic posture rule catalog lives in
[`app/posture/rules.py`](../../backend/app/posture/rules.py). Each rule is a
**pure function of (asset state + graph evidence + policy)**: the same
evidence produces the same outcome, and every finding explains itself from
its own record. No ML (`test_ac04` forbids the imports over the AST, the
Phase 4.5 proof).

A rule returns one of three outcomes per condition:

| Outcome | Meaning |
| --- | --- |
| `FINDING` | the condition holds — open (or sustain) a finding |
| `INSUFFICIENT_DATA` | the rule cannot evaluate — the evidence it needs is absent. Recorded **explicitly**, never a silent "no finding = healthy" (unknown ≠ safe) |
| `CLEAR` | the rule evaluated and the condition does not hold — auto-resolve any open finding for it |

## The catalog

| Rule id | Control | Default severity | Shadow-class | Fires when | Evidence |
| --- | --- | --- | --- | --- | --- |
| `no_accountable_owner` | `OWNERSHIP.ACCOUNTABLE_OWNER` | CRITICAL | | agent has no `owner_id` / `technical_owner_id` / `compliance_owner_id` | `agents` |
| `unowned_with_production_access` | `OWNERSHIP.PRODUCTION_ACCOUNTABILITY` | HIGH | ✓ | unowned **and** has a production deployment or production executions | `agents`, deployments/executions |
| `discovered_outside_lifecycle` | `LIFECYCLE.GOVERNED_ONBOARDING` | HIGH | ✓ | `control_state = DISCOVERED` (never claimed / governed) | `agents.control_state` |
| `unmanaged_external_agent` | `LIFECYCLE.EXTERNAL_ENROLLMENT` | HIGH | ✓ | `origin_category = EXTERNAL` and `control_state ∈ {DISCOVERED, CLAIMED}` | `agents` |
| `production_activity_without_governance` | `GOVERNANCE.PRODUCTION_ENROLLMENT` | HIGH | ✓ | production activity but not `GOVERNED` with an applicable policy | `agents`, deployments, `runtime_governance_policies` |
| `missing_runtime_governance_policy` | `GOVERNANCE.POLICY_COVERAGE` | WARNING (HIGH if `GOVERNED`) | | ACTIVE agent, no enabled governance policy applies | `runtime_governance_policies` (absence) |
| `missing_slo` | `RELIABILITY.SLO_COVERAGE` | WARNING | | ACTIVE production agent, no agent- or org-scoped SLO | `slo_definitions` (absence) |
| `expired_credential_still_active` | `CREDENTIAL.EXPIRY` | CRITICAL | | an ACTIVE `agent_api_keys` row past its `expires_at` | `agent_api_keys` |
| `stale_credential` | `CREDENTIAL.ROTATION` | HIGH | | ACTIVE key, `last_used_at` (or `created_at`) older than `max_age_days` (default 90) | `agent_api_keys` |
| `dormant_agent_with_active_credential` | `CREDENTIAL.LEAST_STANDING` | HIGH | | no executions in `dormant_days` (default 60) but holds ACTIVE keys | `agents`, executions, `agent_api_keys` |
| `unknown_provenance` | `PROVENANCE.ESTABLISHED_ORIGIN` | WARNING | | `origin_category = UNKNOWN`, or EXTERNAL with no `origin_provider` | `agents` |
| `unapproved_mcp_dependency` | `SUPPLY_CHAIN.MCP_TRUST` | HIGH | | a live `DEPENDS_ON_MCP_SERVER` edge to an `mcp_servers` row whose `trust_status ≠ APPROVED` | `control_graph_edges`, `mcp_servers` |
| `dangerous_dependency` | `BLAST_RADIUS.SENSITIVE_RESOURCE` | HIGH | | the agent can reach a resource of a sensitive kind (default `payroll` / `customer_financial` / `pii` / `secrets`) through its dependency graph | `control_graph_edges`, `resources`; **`INSUFFICIENT_DATA` if the agent has no dependency edges at all** |
| `prohibited_model` | `MODEL.APPROVED_MODELS` | HIGH | | the published version's model / provider is on the org's prohibited list (param) | `agent_versions.model_configuration` |
| `unapproved_tool` | `TOOL.APPROVED_GRANTS` | WARNING | | an ACTIVE agent has an `agent_tools` assignment not in status `APPROVED` | `agent_tools` |
| `excessive_tool_scope` | `TOOL.LEAST_PRIVILEGE` | WARNING | | the agent depends on more than `max_tools` (default 15) tools | `control_graph_edges` |

**Shadow rules** are the ✓ subset. "Shadow agents" = agents with an open
finding whose `rule_id` is in that set —
[`app/posture/shadow.py`](../../backend/app/posture/shadow.py), never a
column.

## Evidence gaps — recorded, not fabricated

Two rules the SRS names are **not** delivered because the current evidence
does not support a deterministic version:

- **"excessive privilege" (RBAC)** — an agent does not hold RBAC role
  assignments (roles bind to users). The privilege-scope concern is covered
  by `excessive_tool_scope` and `unapproved_tool` instead.
- **"excessive delegated authority"** — Phase 5.3's delegation edges are
  human↔human; there is no agent-held delegation to measure.

Fabricating a finding from a signal that is not there would violate
"unknown ≠ safe, but also ≠ a fabricated finding". When the evidence lands
(e.g. a future phase records agent-scoped grants), these become rules.

## Tuning

`GET /api/v1/posture/rules` lists every rule with its effective settings.
`PUT /api/v1/posture/rules/{rule_id}` (permission `posture.manage`) enables /
disables a rule or overrides its parameters for the organization. Every
change carries a monotonic `revision` and a `POSTURE_RULE_SETTING_CHANGED`
audit event, so a posture score stays reconstructable and a threshold change
is explainable (SRS §12). Disabling a rule auto-resolves its open findings;
re-enabling re-opens them on the next evaluation.
