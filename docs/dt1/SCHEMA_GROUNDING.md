# SCHEMA_GROUNDING — DT1 Stage 1 (live inspection, read-only)

`schema_grounding_version` = `bee4a00b55c813209ca3d59d01734a2117caed92f7a527916070eecdf53409c3` (SHA-256 of the canonical JSON in `lab/dt1/artifacts/schema_grounding.json`, which excludes this hash and the timestamp).

## Repository state at grounding

- **head**: `ab27fe3a70e72bc3981e9b63afe36eacd5ce90c7`
- **branch**: `validation/v10-authorization-template`
- **main**: `966770711c169265e2bf671dbb7d423f74d83d80`
- **origin_main**: `966770711c169265e2bf671dbb7d423f74d83d80`
- **head_is_ancestor_of_main**: `False`
- **migration_files_head**: `0061_assurance_evidence`
- **instruction_sha256**: `DT1_S1_V2_INSTRUCTION.md` = `984688a1ee563fa8…`, `DT1_S1_V2_PROMPT_APPROVED.md` = `761c9decc7acdefa…`

## Constant vocabularies (AST scan of source, file:line)

- `app/models/graph.py:52` **NODE_TYPES** = `["HUMAN", "AGENT", "AGENT_IDENTITY", "SERVICE_ACCOUNT", "FEDERATED_IDENTITY", "EXTERNAL_CLIENT", "TOOL", "CREDENTIAL", "RESOURCE", "ORGANIZATION", "MCP_SERVER", "CONNECTOR"]`
- `app/models/graph.py:80` **EDGE_TYPES** = `["DELEGATES_TO", "AGENT_DELEGATES_TO", "TRUSTS", "ACTS_AS", "DEPENDS_ON_TOOL", "DEPENDS_ON_MCP_SERVER", "DEPENDS_ON_CREDENTIAL", "DEPENDS_ON_CONNECTOR", "DEPENDS_ON_RESOURCE", "MCP_EXPOSES_TOOL", "TOOL_USES_CREDENTIAL", "TOOL_ACCESSES_RESOURCE", "CREDENTIAL_ACCESSES_RESOURCE"]`
- `app/models/graph.py:99` **DEPENDENCY_EDGE_TYPES** = `["DEPENDS_ON_TOOL", "DEPENDS_ON_MCP_SERVER", "DEPENDS_ON_CREDENTIAL", "DEPENDS_ON_CONNECTOR", "DEPENDS_ON_RESOURCE", "MCP_EXPOSES_TOOL", "TOOL_USES_CREDENTIAL", "TOOL_ACCESSES_RESOURCE", "CREDENTIAL_ACCESSES_RESOURCE"]`
- `app/models/graph.py:115` **EDGE_PROVENANCE** = `["EXPLICIT", "DERIVED", "DISCOVERED"]`
- `app/models/graph.py:119` **MCP_TRUST_STATUSES** = `["APPROVED", "PENDING", "REJECTED", "UNKNOWN"]`
- `app/models/graph.py:120` **MCP_PROVENANCE** = `["EXPLICIT", "DERIVED", "DISCOVERED"]`
- `app/models/discovery.py:42` **RUN_STATUSES** = `["PENDING", "RUNNING", "SUCCEEDED", "PARTIAL", "FAILED"]`
- `app/models/discovery.py:43` **RUN_TRIGGERS** = `["SCHEDULED", "MANUAL"]`
- `app/models/discovery.py:44` **RECONCILIATION_ACTIONS** = `["CREATED", "LINKED"]`
- `app/models/discovery.py:45` **FINDING_TYPES** = `["RECONCILIATION_AMBIGUOUS", "STALE_AGENT"]`
- `app/models/discovery.py:46` **FINDING_STATUSES** = `["OPEN", "RESOLVED", "DISMISSED"]`
- `app/models/bridge.py:72` **STORABLE_ENFORCEMENT_MODES** = `["OBSERVED", "ADVISORY", "GATEWAY_ENFORCED"]`
- `app/models/bridge.py:75` **GATEWAY_OUTCOMES** = `["ALLOWED", "DENIED"]`
- `app/models/bridge.py:80` **DISPATCH_STATUSES** = `["NOT_DISPATCHED", "DISPATCHED", "DISPATCH_FAILED"]`
- `app/models/bridge.py:83` **FAIL_MODES** = `["FAIL_CLOSED", "FAIL_OPEN"]`
- `app/models/bridge.py:87` **POLICY_OUTCOMES** = `["NOT_APPLICABLE", "SATISFIED", "APPROVAL_REQUIRED", "UNEVALUABLE"]`
- `app/models/bridge.py:91` **COST_OUTCOMES** = `["NOT_MEASURABLE", "WITHIN_BUDGET", "EXCEEDED", "UNEVALUABLE"]`
- `app/models/threat.py:43` **THREAT_SEVERITIES** = `["INFO", "WARNING", "HIGH", "CRITICAL"]`
- `app/models/threat.py:44` **THREAT_STATUSES** = `["OPEN", "ACKNOWLEDGED", "RESOLVED", "SUPPRESSED"]`
- `app/models/threat.py:45` **THREAT_OUTCOMES** = `["FINDING", "INSUFFICIENT_DATA"]`
- `app/models/threat.py:51` **CONTAINMENT_ACTION_TYPES** = `["TERMINATE_EXECUTION", "SUSPEND_AGENT", "DENY_TOOL", "REVOKE_CAPABILITY", "ISOLATE_CREDENTIAL", "DISABLE_INTEGRATION", "REQUIRE_APPROVAL"]`
- `app/models/threat.py:61` **CONTAINMENT_AUTHORITIES** = `["KILL_SWITCH", "GOVERNANCE_POLICY", "TOOL_LIFECYCLE", "CAPABILITY_LIFECYCLE", "CREDENTIAL_LIFECYCLE", "CONNECTOR_LIFECYCLE"]`
- `app/models/threat.py:65` **CONTAINMENT_TRIGGERS** = `["THREAT", "OPERATOR"]`
- `app/models/threat.py:81` **CONTAINMENT_ACTION_STATUSES** = `["RECOMMENDED", "PENDING_CONFIRMATION", "EXECUTED", "REFUSED", "FAILED", "REVERTED"]`
- `app/models/posture.py:47` **POSTURE_SEVERITIES** = `["INFO", "WARNING", "HIGH", "CRITICAL"]`
- `app/models/posture.py:48` **POSTURE_STATUSES** = `["OPEN", "ACKNOWLEDGED", "RESOLVED", "SUPPRESSED"]`
- `app/models/posture.py:53` **POSTURE_OUTCOMES** = `["FINDING", "INSUFFICIENT_DATA"]`
- `app/runtime/registry/control.py:55` **CONTROL_STATES** = `["DISCOVERED", "CLAIMED", "REGISTERED", "GOVERNED"]`
- `app/runtime/registry/control.py:58` **ORIGIN_CATEGORIES** = `["NATIVE", "EXTERNAL", "UNKNOWN"]`
- `app/runtime/registry/control.py:62` **ORIGIN_PROVIDERS** = `["ACT_NATIVE", "MICROSOFT", "AWS", "GOOGLE", "OPENAI", "ANTHROPIC", "LANGGRAPH", "CREWAI", "CUSTOM", "UNKNOWN"]`
- `app/runtime/registry/control.py:90` **LEGAL_CONTROL_STATES_BY_ORIGIN** = `{"NATIVE": ["GOVERNED"], "EXTERNAL": ["DISCOVERED", "CLAIMED", "REGISTERED"], "UNKNOWN": ["DISCOVERED", "CLAIMED", "REGISTERED"]}`
- `app/runtime/registry/services.py:52` **EDITABLE_STATES** = `["DRAFT", "REGISTERED", "VALIDATION_FAILED", "REJECTED"]`
- `app/runtime/registry/services.py:54` **_TIMESTAMP_FIELD** = `{"VALIDATED": "validated_at", "APPROVED": "approved_at", "ACTIVE": "activated_at", "SUSPENDED": "suspended_at", "ARCHIVED": "archived_at", "RETIRED": "retired_at"}`
- `app/runtime/services.py:112` **AGENT_LIFECYCLE** = `["DRAFT", "REGISTERED", "VALIDATING", "VALIDATION_FAILED", "VALIDATED", "PENDING_APPROVAL", "REJECTED", "APPROVED", "ACTIVE", "SUSPENDED", "DEPRECATED", "ARCHIVED", "RETIRED"]`
- `app/runtime/services.py:115` **VERSION_LIFECYCLE** = `["DRAFT", "VALIDATING", "READY_FOR_REVIEW", "APPROVED", "PUBLISHED", "DEPRECATED", "REVOKED", "RETIRED"]`
- `app/runtime/services.py:117` **DEPLOYMENT_LIFECYCLE** = `["CREATED", "PENDING_APPROVAL", "SCHEDULED", "DEPLOYING", "HEALTH_CHECKING", "ACTIVE", "DEGRADED", "FAILED", "SUSPENDED", "ROLLING_BACK", "RETIRED"]`
- `app/runtime/services.py:120` **TERMINAL_EXECUTION_STATUSES** = `["SUCCEEDED", "FAILED", "CANCELLED", "DEAD_LETTERED", "DENIED", "REJECTED", "BLOCKED", "TIMED_OUT"]`
- `app/runtime/services.py:122` **ACTIVE_EXECUTION_STATUSES** = `["CREATED", "AUTHORIZING", "PENDING_APPROVAL", "QUEUED", "SCHEDULED", "RUNNING"]`
- `app/runtime/services.py:129` **_EXECUTION_TRANSITIONS** = `{"CREATED": ["AUTHORIZING", "CANCELLED"], "AUTHORIZING": ["DENIED", "BLOCKED", "PENDING_APPROVAL", "QUEUED", "CANCELLED"], "PENDING_APPROVAL": ["QUEUED", "REJECTED", "CANCELLED"], "QUEUED": ["RUNNING", "CANCELLED"], "SCHEDULED": ["QUEUED", "RUNNING", "CANCELLED"], "RUNNING": ["SUCCEEDED", "FAILED", "QUEUED", "DEAD_LETTERED", "TIMED_OUT", "CANCELLED", "PENDING_APPROVAL", "BLOCKED"], "FAILED": ["QUE…`
- `app/runtime/services.py:163` **_RESERVED_SLUGS** = `["new", "admin", "api", "null", "undefined", "self", "system"]`
- `app/bridge/modes.py:50` **ENFORCEMENT_MODES** = `["OBSERVED", "ADVISORY", "GATEWAY_ENFORCED", "NATIVE_ENFORCED"]`
- `app/bridge/modes.py:58` **SETTABLE_MODES** = `["OBSERVED", "ADVISORY", "GATEWAY_ENFORCED"]`
- `app/bridge/modes.py:63` **NATIVE_CONTROL_STATE** = `"GOVERNED"`
- `app/bridge/capabilities.py:37` **PLANES** = `["GOVERNANCE", "OBSERVABILITY"]`
- `app/graph/traversal.py:34` **MAX_TRAVERSAL_DEPTH** = `32`
- `app/graph/traversal.py:35` **DEFAULT_TRAVERSAL_DEPTH** = `16`
- `app/graph/traversal.py:37` **_DELEGATION_EDGE_TYPES** = `["DELEGATES_TO", "AGENT_DELEGATES_TO"]`
- `app/graph/dependencies.py:44` **_EDGE_SHAPE** = `{"DEPENDS_ON_TOOL": ["AGENT", "TOOL"], "DEPENDS_ON_MCP_SERVER": ["AGENT", "MCP_SERVER"], "DEPENDS_ON_CREDENTIAL": ["AGENT", "CREDENTIAL"], "DEPENDS_ON_CONNECTOR": ["AGENT", "CONNECTOR"], "DEPENDS_ON_RESOURCE": ["AGENT", "RESOURCE"], "MCP_EXPOSES_TOOL": ["MCP_SERVER", "TOOL"], "TOOL_USES_CREDENTIAL": ["TOOL", "CREDENTIAL"], "TOOL_ACCESSES_RESOURCE": ["TOOL", "RESOURCE"], "CREDENTIAL_ACCESSES_RESOUR…`
- `app/discovery/reconciliation.py:54` **LINK_CREATE_CONFIDENCE_THRESHOLD** = `"0.75"`
- `app/discovery/reconciliation.py:66` **_MAX_NAME** = `255`
- `app/threat/containment.py:67` **_ENFORCEABLE_CONTROL_STATE** = `"GOVERNED"`
- `app/threat/containment.py:69` **_AUTHORITY_FOR** = `{"TERMINATE_EXECUTION": "KILL_SWITCH", "SUSPEND_AGENT": "KILL_SWITCH", "DENY_TOOL": "TOOL_LIFECYCLE", "REVOKE_CAPABILITY": "CAPABILITY_LIFECYCLE", "ISOLATE_CREDENTIAL": "CREDENTIAL_LIFECYCLE", "DISABLE_INTEGRATION": "CONNECTOR_LIFECYCLE", "REQUIRE_APPROVAL": "GOVERNANCE_POLICY"}`
- `app/threat/containment.py:84` **_REVERSIBLE** = `{"TERMINATE_EXECUTION": false, "SUSPEND_AGENT": false, "DENY_TOOL": true, "REVOKE_CAPABILITY": true, "ISOLATE_CREDENTIAL": false, "DISABLE_INTEGRATION": true, "REQUIRE_APPROVAL": true}`
- `app/discovery/adapters/http_agent_registry.py:40` **ADAPTER_KEY** = `"HTTP_AGENT_REGISTRY"`
- `app/discovery/adapters/aws_bedrock_agents.py:87` **ADAPTER_KEY** = `"AWS_BEDROCK_AGENTS"`
- `app/discovery/adapters/aws_bedrock_agents.py:91` **SIGNING_NAME** = `"bedrock"`
- `app/discovery/adapters/aws_bedrock_agents.py:92` **LIST_AGENTS_METHOD** = `"POST"`
- `app/discovery/adapters/aws_bedrock_agents.py:93` **LIST_AGENTS_PATH** = `"/agents/"`
- `app/discovery/adapters/aws_bedrock_agents.py:97` **REQUIRED_IAM_ACTIONS** = `["bedrock:ListAgents"]`
- `app/discovery/adapters/aws_bedrock_agents.py:102` **KNOWN_AGENT_STATUSES** = `["CREATING", "PREPARING", "PREPARED", "NOT_PREPARED", "DELETING", "FAILED", "VERSIONING", "UPDATING"]`
- `app/discovery/adapters/aws_bedrock_agents.py:105` **EXCLUDED_AGENT_STATUSES** = `["DELETING"]`

## Tables (Base.metadata introspection — columns, constraints)

### `organizations` (8 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `name` | VARCHAR(255) | False | None |  |
| `slug` | VARCHAR(120) | True | None |  |
| `owner_id` | UUID | True | None | users.id |
| `status` | VARCHAR(30) | False | 'ACTIVE' |  |
| `registration_mode` | VARCHAR(20) | False | 'INVITE_ONLY' |  |
| `id` | UUID | False | '<callable>' |  |
| `created_at` | DATETIME | False | None |  |
| `updated_at` | DATETIME | False | None |  |

### `users` (15 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | False | None | organizations.id |
| `department_id` | UUID | True | None | departments.id |
| `name` | VARCHAR(255) | False | None |  |
| `email` | VARCHAR(320) | False | None |  |
| `password_hash` | VARCHAR(255) | False | None |  |
| `role` | VARCHAR(11) | False | 'VIEWER' |  |
| `is_active` | BOOLEAN | False | True |  |
| `status` | VARCHAR(30) | False | 'ACTIVE' |  |
| `password_changed_at` | DATETIME | True | None |  |
| `password_expires_at` | DATETIME | True | None |  |
| `must_change_password` | BOOLEAN | False | False |  |
| `pending_email` | VARCHAR(320) | True | None |  |
| `id` | UUID | False | '<callable>' |  |
| `created_at` | DATETIME | False | None |  |
| `updated_at` | DATETIME | False | None |  |

### `agents` (60 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | False | None | organizations.id |
| `name` | VARCHAR(255) | False | None |  |
| `description` | TEXT | True | None |  |
| `agent_type` | VARCHAR(100) | False | None |  |
| `api_key_hash` | VARCHAR(255) | False | None |  |
| `status` | VARCHAR(9) | False | 'ACTIVE' |  |
| `owner` | VARCHAR(255) | True | None |  |
| `department` | VARCHAR(255) | True | None |  |
| `version` | VARCHAR(50) | False | '1.0.0' |  |
| `capabilities` | JSONB | False | '<callable>' |  |
| `default_risk_score` | INTEGER | False | 0 |  |
| `max_allowed_risk` | INTEGER | False | 100 |  |
| `human_approval_required` | BOOLEAN | False | False |  |
| `auto_suspend_threshold` | INTEGER | True | None |  |
| `risk_level` | VARCHAR(20) | False | 'LOW' |  |
| `health` | VARCHAR(20) | False | 'HEALTHY' |  |
| `slug` | VARCHAR(150) | True | None |  |
| `project_id` | UUID | True | None | projects.id |
| `owner_type` | VARCHAR(30) | True | None |  |
| `owner_id` | UUID | True | None |  |
| `criticality` | VARCHAR(20) | False | 'MEDIUM' |  |
| `data_classification` | VARCHAR(30) | False | 'INTERNAL' |  |
| `default_environment` | VARCHAR(20) | False | 'DEVELOPMENT' |  |
| `lifecycle_status` | VARCHAR(20) | False | 'ACTIVE' |  |
| `archived_at` | DATETIME | True | None |  |
| `business_unit_id` | UUID | True | None | business_units.id |
| `department_id` | UUID | True | None | departments.id |
| `team_id` | UUID | True | None | teams.id |
| `identity_id` | UUID | True | None | agent_identities.id |
| `display_name` | VARCHAR(255) | True | None |  |
| `business_purpose` | TEXT | True | None |  |
| `autonomy_level` | VARCHAR(30) | False | 'ASSISTIVE' |  |
| `technical_owner_id` | UUID | True | None | users.id |
| `compliance_owner_id` | UUID | True | None | users.id |
| `support_contact` | VARCHAR(255) | True | None |  |
| `documentation_url` | VARCHAR(500) | True | None |  |
| `repository_url` | VARCHAR(500) | True | None |  |
| `tags` | JSONB | False | '<callable>' |  |
| `metadata` | JSONB | False | '<callable>' |  |
| `registration_source` | VARCHAR(30) | False | 'MANUAL' |  |
| `external_reference` | VARCHAR(255) | True | None |  |
| `created_by` | UUID | True | None | users.id |
| `updated_by` | UUID | True | None | users.id |
| `validated_at` | DATETIME | True | None |  |
| `approved_at` | DATETIME | True | None |  |
| `activated_at` | DATETIME | True | None |  |
| `suspended_at` | DATETIME | True | None |  |
| `retired_at` | DATETIME | True | None |  |
| `row_version` | INTEGER | False | 1 |  |
| `control_state` | VARCHAR(20) | False | 'GOVERNED' |  |
| `origin_category` | VARCHAR(20) | False | 'NATIVE' |  |
| `origin_provider` | VARCHAR(50) | False | 'ACT_NATIVE' |  |
| `external_enforcement_mode` | VARCHAR(20) | True | None |  |
| `first_observed_at` | DATETIME | True | None |  |
| `last_observed_at` | DATETIME | True | None |  |
| `discovery_source_ref` | VARCHAR(255) | True | None |  |
| `discovery_confidence` | NUMERIC(5, 2) | True | None |  |
| `id` | UUID | False | '<callable>' |  |
| `created_at` | DATETIME | False | None |  |
| `updated_at` | DATETIME | False | None |  |
CHECK: `control_state IN ('DISCOVERED', 'CLAIMED', 'REGISTERED', 'GOVERNED')` · `external_enforcement_mode IS NULL OR external_enforcement_mode IN ('OBSERVED', 'ADVISORY', 'GATEWAY_ENFORCED')` · `origin_category IN ('NATIVE', 'EXTERNAL', 'UNKNOWN')`
UNIQUE: `organization_id,external_reference` · `organization_id,slug`

### `agent_identities` (9 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `agent_id` | UUID | False | None | agents.id |
| `client_id` | VARCHAR(100) | False | None |  |
| `credential_type` | VARCHAR(30) | False | 'API_KEY' |  |
| `status` | VARCHAR(30) | False | 'ACTIVE' |  |
| `last_used_at` | DATETIME | True | None |  |
| `expires_at` | DATETIME | True | None |  |
| `id` | UUID | False | '<callable>' |  |
| `created_at` | DATETIME | False | None |  |
| `updated_at` | DATETIME | False | None |  |
UNIQUE: `agent_id`

### `service_accounts` (9 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | False | None | organizations.id |
| `name` | VARCHAR(255) | False | None |  |
| `client_secret_hash` | VARCHAR(255) | False | None |  |
| `permissions` | JSONB | False | '<callable>' |  |
| `owner_id` | UUID | True | None | users.id |
| `status` | VARCHAR(30) | False | 'ACTIVE' |  |
| `id` | UUID | False | '<callable>' |  |
| `created_at` | DATETIME | False | None |  |
| `updated_at` | DATETIME | False | None |  |

### `external_clients` (10 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | False | None | organizations.id |
| `client_name` | VARCHAR(255) | False | None |  |
| `client_id` | VARCHAR(100) | False | None |  |
| `redirect_uri` | VARCHAR(2048) | True | None |  |
| `secret_hash` | VARCHAR(255) | False | None |  |
| `allowed_scopes` | JSONB | False | '<callable>' |  |
| `status` | VARCHAR(30) | False | 'ACTIVE' |  |
| `id` | UUID | False | '<callable>' |  |
| `created_at` | DATETIME | False | None |  |
| `updated_at` | DATETIME | False | None |  |

### `federated_identities` (8 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `user_id` | UUID | False | None | users.id |
| `organization_id` | UUID | False | None | organizations.id |
| `federation_config_id` | UUID | False | None | identity_federation_configs.id |
| `external_subject_id` | VARCHAR(255) | False | None |  |
| `last_federated_login_at` | DATETIME | True | None |  |
| `id` | UUID | False | '<callable>' |  |
| `created_at` | DATETIME | False | None |  |
| `updated_at` | DATETIME | False | None |  |

### `delegations` (9 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | False | None | organizations.id |
| `delegator_id` | UUID | True | None |  |
| `delegatee_id` | UUID | False | None | users.id |
| `scope_type` | VARCHAR(20) | False | None |  |
| `scope_id` | UUID | True | None |  |
| `permission` | VARCHAR(100) | True | None |  |
| `created_at` | DATETIME | False | None |  |
| `revoked_at` | DATETIME | True | None |  |
| `id` | UUID | False | '<callable>' |  |

### `tools` (20 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | True | None | organizations.id |
| `name` | VARCHAR(100) | False | None |  |
| `display_name` | VARCHAR(150) | False | None |  |
| `description` | TEXT | True | None |  |
| `tool_type` | VARCHAR(30) | False | 'FUNCTION' |  |
| `endpoint_reference` | VARCHAR(500) | True | None |  |
| `input_schema` | JSONB | True | None |  |
| `output_schema` | JSONB | True | None |  |
| `risk_level` | VARCHAR(20) | False | 'MEDIUM' |  |
| `side_effect_level` | VARCHAR(20) | False | 'NONE' |  |
| `data_classification` | VARCHAR(30) | False | 'INTERNAL' |  |
| `requires_approval` | BOOLEAN | False | False |  |
| `timeout_seconds` | INTEGER | False | 30 |  |
| `enabled` | BOOLEAN | False | True |  |
| `http_config` | JSONB | True | None |  |
| `mcp_server_id` | UUID | True | None | mcp_servers.id |
| `created_by` | UUID | True | None |  |
| `created_at` | DATETIME | False | None |  |
| `updated_at` | DATETIME | False | None |  |
| `id` | UUID | False | '<callable>' |  |

### `tool_credentials` (9 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | False | None | organizations.id |
| `tool_id` | UUID | False | None | tools.id |
| `encrypted_secret` | TEXT | False | None |  |
| `secret_hint` | VARCHAR(8) | False | None |  |
| `status` | VARCHAR(20) | False | 'ACTIVE' |  |
| `created_by` | UUID | True | None | users.id |
| `created_at` | DATETIME | False | None |  |
| `updated_at` | DATETIME | False | None |  |
| `id` | UUID | False | '<callable>' |  |
UNIQUE: `organization_id,tool_id`

### `provider_credentials` (11 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | False | None | organizations.id |
| `provider` | VARCHAR(64) | False | None |  |
| `encrypted_secret` | TEXT | False | None |  |
| `secret_hint` | VARCHAR(8) | False | None |  |
| `base_url` | TEXT | True | None |  |
| `status` | VARCHAR(20) | False | 'ACTIVE' |  |
| `created_by` | UUID | True | None | users.id |
| `last_used_at` | DATETIME | True | None |  |
| `created_at` | DATETIME | False | None |  |
| `updated_at` | DATETIME | False | None |  |
| `id` | UUID | False | '<callable>' |  |
UNIQUE: `organization_id,provider`

### `connector_credentials` (12 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `connector_instance_id` | UUID | False | None | connector_instances.id |
| `organization_id` | UUID | False | None | organizations.id |
| `auth_scheme` | VARCHAR(48) | False | None |  |
| `encrypted_secret` | TEXT | False | None |  |
| `secret_hint` | VARCHAR(8) | False | None |  |
| `status` | VARCHAR(20) | False | 'ACTIVE' |  |
| `last_validated_at` | DATETIME | True | None |  |
| `validation_status` | VARCHAR(20) | True | None |  |
| `created_at` | DATETIME | False | None |  |
| `updated_at` | DATETIME | False | None |  |
| `created_by` | UUID | True | None | users.id |
| `id` | UUID | False | '<callable>' |  |
UNIQUE: `connector_instance_id,auth_scheme`

### `mcp_servers` (16 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | False | None | organizations.id |
| `name` | VARCHAR(255) | False | None |  |
| `description` | VARCHAR(2000) | True | None |  |
| `provenance` | VARCHAR(24) | False | 'EXPLICIT' |  |
| `trust_status` | VARCHAR(24) | False | 'PENDING' |  |
| `version` | VARCHAR(64) | True | None |  |
| `endpoint_reference` | VARCHAR(500) | True | None |  |
| `declared_capabilities` | JSONB | False | '<callable>' |  |
| `owner_id` | UUID | True | None |  |
| `owner_type` | VARCHAR(30) | True | None |  |
| `last_probed_at` | DATETIME | True | None |  |
| `probe_status` | VARCHAR(24) | True | None |  |
| `created_by` | UUID | True | None |  |
| `created_at` | DATETIME | False | None |  |
| `updated_at` | DATETIME | False | None |  |
| `id` | UUID | False | '<callable>' |  |
CHECK: `provenance IN ('EXPLICIT', 'DERIVED', 'DISCOVERED')` · `trust_status IN ('APPROVED', 'PENDING', 'REJECTED', 'UNKNOWN')`

### `resources` (14 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `resource_type` | VARCHAR(50) | False | None |  |
| `resource_id` | UUID | False | None |  |
| `name` | VARCHAR(255) | True | None |  |
| `organization_id` | UUID | False | None | organizations.id |
| `project_id` | UUID | True | None |  |
| `owner_id` | UUID | False | None |  |
| `owner_type` | VARCHAR(20) | False | 'USER' |  |
| `created_by` | UUID | True | None |  |
| `visibility` | VARCHAR(20) | False | 'PRIVATE' |  |
| `status` | VARCHAR(20) | False | 'ACTIVE' |  |
| `policy` | JSONB | True | None |  |
| `id` | UUID | False | '<callable>' |  |
| `created_at` | DATETIME | False | None |  |
| `updated_at` | DATETIME | False | None |  |
UNIQUE: `resource_type,resource_id`

### `control_graph_edges` (17 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | False | None | organizations.id |
| `source_type` | VARCHAR(32) | False | None |  |
| `source_id` | UUID | False | None |  |
| `edge_type` | VARCHAR(40) | False | None |  |
| `target_type` | VARCHAR(32) | False | None |  |
| `target_id` | UUID | False | None |  |
| `evidence` | JSONB | False | '<callable>' |  |
| `confidence` | NUMERIC(3, 2) | False | '1.00' |  |
| `provenance` | VARCHAR(24) | False | 'EXPLICIT' |  |
| `valid_from` | DATETIME | False | None |  |
| `valid_until` | DATETIME | True | None |  |
| `revoked_at` | DATETIME | True | None |  |
| `revoked_by` | UUID | True | None |  |
| `created_by` | UUID | True | None |  |
| `id` | UUID | False | '<callable>' |  |
| `created_at` | DATETIME | False | None |  |
| `updated_at` | DATETIME | False | None |  |
CHECK: `NOT (source_type = target_type AND source_id = target_id)` · `confidence >= 0 AND confidence <= 1` · `edge_type IN ('DELEGATES_TO', 'AGENT_DELEGATES_TO', 'TRUSTS', 'ACTS_AS', 'DEPENDS_ON_TOOL', 'DEPENDS_ON_MCP_SERVER', 'DEPENDS_ON_CREDENTIAL'` · `provenance IN ('EXPLICIT', 'DERIVED', 'DISCOVERED')` · `source_type IN ('HUMAN', 'AGENT', 'AGENT_IDENTITY', 'SERVICE_ACCOUNT', 'FEDERATED_IDENTITY', 'EXTERNAL_CLIENT', 'TOOL', 'CREDENTIAL', 'RESOU` · `target_type IN ('HUMAN', 'AGENT', 'AGENT_IDENTITY', 'SERVICE_ACCOUNT', 'FEDERATED_IDENTITY', 'EXTERNAL_CLIENT', 'TOOL', 'CREDENTIAL', 'RESOU`

### `discovery_sources` (14 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | False | None | organizations.id |
| `name` | VARCHAR(255) | False | None |  |
| `adapter_key` | VARCHAR(64) | False | None |  |
| `config` | JSONB | False | '<callable>' |  |
| `encrypted_secret` | TEXT | True | None |  |
| `secret_hint` | VARCHAR(20) | True | None |  |
| `enabled` | BOOLEAN | False | True |  |
| `missed_sweeps_before_stale` | INTEGER | False | 1 |  |
| `last_run_at` | DATETIME | True | None |  |
| `last_run_status` | VARCHAR(16) | True | None |  |
| `created_by` | UUID | True | None |  |
| `id` | UUID | False | '<callable>' |  |
| `created_at` | DATETIME | False | None |  |
| `updated_at` | DATETIME | False | None |  |
UNIQUE: `organization_id,name`

### `discovery_runs` (14 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | False | None | organizations.id |
| `source_id` | UUID | False | None | discovery_sources.id |
| `status` | VARCHAR(16) | False | 'PENDING' |  |
| `trigger` | VARCHAR(16) | False | 'SCHEDULED' |  |
| `started_at` | DATETIME | True | None |  |
| `ended_at` | DATETIME | True | None |  |
| `checkpoint` | JSONB | False | '<callable>' |  |
| `observations_count` | INTEGER | False | 0 |  |
| `agents_created` | INTEGER | False | 0 |  |
| `agents_linked` | INTEGER | False | 0 |  |
| `findings_created` | INTEGER | False | 0 |  |
| `error` | TEXT | True | None |  |
| `created_at` | DATETIME | False | None |  |
| `id` | UUID | False | '<callable>' |  |
CHECK: `status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED')` · `trigger IN ('SCHEDULED', 'MANUAL')`

### `discovery_observations` (9 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | False | None | organizations.id |
| `source_id` | UUID | False | None | discovery_sources.id |
| `run_id` | UUID | False | None | discovery_runs.id |
| `external_identifier` | VARCHAR(500) | False | None |  |
| `normalized_payload` | JSONB | False | '<callable>' |  |
| `confidence` | NUMERIC(3, 2) | False | '1.00' |  |
| `observed_at` | DATETIME | False | None |  |
| `created_at` | DATETIME | False | None |  |
| `id` | UUID | False | '<callable>' |  |
CHECK: `confidence >= 0 AND confidence <= 1`

### `discovery_findings` (14 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | False | None | organizations.id |
| `finding_type` | VARCHAR(30) | False | None |  |
| `source_id` | UUID | True | None | discovery_sources.id |
| `run_id` | UUID | True | None | discovery_runs.id |
| `observation_id` | UUID | True | None | discovery_observations.id |
| `agent_id` | UUID | True | None | agents.id |
| `external_identifier` | VARCHAR(500) | True | None |  |
| `confidence` | NUMERIC(3, 2) | True | None |  |
| `reason` | TEXT | False | None |  |
| `status` | VARCHAR(16) | False | 'OPEN' |  |
| `resolved_by` | UUID | True | None |  |
| `resolved_at` | DATETIME | True | None |  |
| `created_at` | DATETIME | False | None |  |
| `id` | UUID | False | '<callable>' |  |
CHECK: `finding_type IN ('RECONCILIATION_AMBIGUOUS', 'STALE_AGENT')` · `status IN ('OPEN', 'RESOLVED', 'DISMISSED')`

### `posture_findings` (27 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | False | None | organizations.id |
| `rule_id` | VARCHAR(64) | False | None |  |
| `control_id` | VARCHAR(64) | True | None |  |
| `rule_version` | VARCHAR(16) | False | '1' |  |
| `ruleset_version` | VARCHAR(16) | False | '1' |  |
| `outcome` | VARCHAR(20) | False | 'FINDING' |  |
| `severity` | VARCHAR(12) | False | 'WARNING' |  |
| `status` | VARCHAR(16) | False | 'OPEN' |  |
| `subject_type` | VARCHAR(24) | False | 'AGENT' |  |
| `subject_id` | UUID | False | None |  |
| `reason` | TEXT | False | None |  |
| `remediation` | TEXT | False | '' |  |
| `evidence` | JSONB | False | '<callable>' |  |
| `governing_policy` | JSONB | False | '<callable>' |  |
| `dedup_key` | VARCHAR(180) | False | None |  |
| `recurrence_count` | INTEGER | False | 1 |  |
| `first_seen_at` | DATETIME | False | None |  |
| `last_seen_at` | DATETIME | False | None |  |
| `acknowledged_at` | DATETIME | True | None |  |
| `acknowledged_by` | UUID | True | None |  |
| `resolved_at` | DATETIME | True | None |  |
| `resolved_by` | UUID | True | None |  |
| `suppressed_at` | DATETIME | True | None |  |
| `suppressed_by` | UUID | True | None |  |
| `created_at` | DATETIME | False | None |  |
| `updated_at` | DATETIME | False | None |  |
| `id` | UUID | False | '<callable>' |  |
CHECK: `outcome IN ('FINDING', 'INSUFFICIENT_DATA')` · `severity IN ('INFO', 'WARNING', 'HIGH', 'CRITICAL')` · `status IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'SUPPRESSED')`

### `threat_findings` (24 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | False | None | organizations.id |
| `rule_id` | VARCHAR(64) | False | None |  |
| `rule_version` | VARCHAR(16) | False | '1' |  |
| `ruleset_version` | VARCHAR(16) | False | '1' |  |
| `outcome` | VARCHAR(20) | False | 'FINDING' |  |
| `severity` | VARCHAR(12) | False | 'WARNING' |  |
| `status` | VARCHAR(16) | False | 'OPEN' |  |
| `agent_id` | UUID | False | None | agents.id |
| `reason` | TEXT | False | None |  |
| `attribution` | JSONB | False | '<callable>' |  |
| `evidence` | JSONB | False | '<callable>' |  |
| `dedup_key` | VARCHAR(180) | False | None |  |
| `recurrence_count` | INTEGER | False | 1 |  |
| `first_seen_at` | DATETIME | False | None |  |
| `last_seen_at` | DATETIME | False | None |  |
| `acknowledged_at` | DATETIME | True | None |  |
| `acknowledged_by` | UUID | True | None |  |
| `resolved_at` | DATETIME | True | None |  |
| `resolved_by` | UUID | True | None |  |
| `suppressed_at` | DATETIME | True | None |  |
| `suppressed_by` | UUID | True | None |  |
| `created_at` | DATETIME | False | None |  |
| `updated_at` | DATETIME | False | None |  |
| `id` | UUID | False | '<callable>' |  |
CHECK: `outcome IN ('FINDING', 'INSUFFICIENT_DATA')` · `severity IN ('INFO', 'WARNING', 'HIGH', 'CRITICAL')` · `status IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'SUPPRESSED')`

### `containment_actions` (25 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | False | None | organizations.id |
| `action_type` | VARCHAR(32) | False | None |  |
| `authority` | VARCHAR(32) | False | None |  |
| `trigger` | VARCHAR(16) | False | None |  |
| `threat_finding_id` | UUID | True | None | threat_findings.id |
| `triggered_by_user_id` | UUID | True | None |  |
| `automated` | BOOLEAN | False | False |  |
| `agent_id` | UUID | False | None | agents.id |
| `target_type` | VARCHAR(32) | True | None |  |
| `target_id` | UUID | True | None |  |
| `control_state_at_time` | VARCHAR(20) | False | None |  |
| `status` | VARCHAR(24) | False | 'RECOMMENDED' |  |
| `requires_confirmation` | BOOLEAN | False | True |  |
| `confirmed_by` | UUID | True | None |  |
| `confirmed_at` | DATETIME | True | None |  |
| `reason` | TEXT | False | None |  |
| `refusal_reason` | TEXT | True | None |  |
| `authority_ref` | JSONB | True | None |  |
| `result` | JSONB | False | '<callable>' |  |
| `reversible` | BOOLEAN | False | False |  |
| `reverted_at` | DATETIME | True | None |  |
| `reverted_by` | UUID | True | None |  |
| `created_at` | DATETIME | False | None |  |
| `updated_at` | DATETIME | False | None |  |
| `id` | UUID | False | '<callable>' |  |
CHECK: `action_type IN ('TERMINATE_EXECUTION', 'SUSPEND_AGENT', 'DENY_TOOL', 'REVOKE_CAPABILITY', 'ISOLATE_CREDENTIAL', 'DISABLE_INTEGRATION', 'REQU` · `authority IN ('KILL_SWITCH', 'GOVERNANCE_POLICY', 'TOOL_LIFECYCLE', 'CAPABILITY_LIFECYCLE', 'CREDENTIAL_LIFECYCLE', 'CONNECTOR_LIFECYCLE')` · `status IN ('RECOMMENDED', 'PENDING_CONFIRMATION', 'EXECUTED', 'REFUSED', 'FAILED', 'REVERTED')` · `trigger IN ('THREAT', 'OPERATOR')`

### `external_capability_grants` (16 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | False | None | organizations.id |
| `agent_id` | UUID | False | None | agents.id |
| `label` | VARCHAR(100) | False | None |  |
| `key_id` | VARCHAR(64) | False | None |  |
| `secret_ciphertext` | TEXT | False | None |  |
| `secret_hint` | VARCHAR(32) | False | None |  |
| `scope` | JSONB | False | '<callable>' |  |
| `expires_at` | DATETIME | True | None |  |
| `revoked_at` | DATETIME | True | None |  |
| `revoked_by` | UUID | True | None |  |
| `revocation_reason` | TEXT | True | None |  |
| `rate_limit_per_minute` | INTEGER | False | 60 |  |
| `created_by` | UUID | True | None |  |
| `last_used_at` | DATETIME | True | None |  |
| `created_at` | DATETIME | False | None |  |
| `id` | UUID | False | '<callable>' |  |
CHECK: `rate_limit_per_minute > 0`
UNIQUE: `key_id` · `organization_id,agent_id,label`

### `external_gateway_calls` (22 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | False | None | organizations.id |
| `agent_id` | UUID | False | None | agents.id |
| `grant_id` | UUID | True | None | external_capability_grants.id |
| `capability_key` | VARCHAR(64) | False | None |  |
| `target_ref` | VARCHAR(255) | True | None |  |
| `enforcement_mode_at_time` | VARCHAR(20) | False | None |  |
| `authz_decision` | VARCHAR(32) | False | None |  |
| `authz_permission` | VARCHAR(128) | False | None |  |
| `authz_reason` | TEXT | True | None |  |
| `authz_request_id` | VARCHAR(128) | True | None |  |
| `policy_outcome` | VARCHAR(24) | False | None |  |
| `policy_detail` | JSONB | True | None |  |
| `cost_outcome` | VARCHAR(24) | False | None |  |
| `cost_detail` | JSONB | True | None |  |
| `outcome` | VARCHAR(16) | False | None |  |
| `denial_reason` | TEXT | True | None |  |
| `fail_mode` | VARCHAR(16) | False | None |  |
| `dispatch_status` | VARCHAR(24) | False | 'NOT_DISPATCHED' |  |
| `dispatch_detail` | JSONB | True | None |  |
| `idempotency_key` | VARCHAR(128) | True | None |  |
| `created_at` | DATETIME | False | None |  |
| `id` | UUID | False | '<callable>' |  |
CHECK: `cost_outcome IN ('NOT_MEASURABLE', 'WITHIN_BUDGET', 'EXCEEDED', 'UNEVALUABLE')` · `dispatch_status IN ('NOT_DISPATCHED', 'DISPATCHED', 'DISPATCH_FAILED')` · `fail_mode IN ('FAIL_CLOSED', 'FAIL_OPEN')` · `outcome = 'ALLOWED' OR dispatch_status = 'NOT_DISPATCHED'` · `outcome IN ('ALLOWED', 'DENIED')` · `policy_outcome IN ('NOT_APPLICABLE', 'SATISFIED', 'APPROVAL_REQUIRED', 'UNEVALUABLE')`

### `external_request_nonces` (6 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | False | None | organizations.id |
| `grant_id` | UUID | False | None | external_capability_grants.id |
| `nonce` | VARCHAR(128) | False | None |  |
| `expires_at` | DATETIME | False | None |  |
| `created_at` | DATETIME | False | None |  |
| `id` | UUID | False | '<callable>' |  |
UNIQUE: `grant_id,nonce`

### `agent_executions` (45 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | False | None | organizations.id |
| `agent_id` | UUID | False | None | agents.id |
| `agent_version_id` | UUID | False | None | agent_versions.id |
| `deployment_id` | UUID | True | None | agent_deployments.id |
| `trigger_type` | VARCHAR(20) | False | 'API' |  |
| `triggered_by_identity_id` | UUID | True | None |  |
| `parent_execution_id` | UUID | True | None | agent_executions.id |
| `correlation_id` | VARCHAR(100) | True | None |  |
| `request_id` | VARCHAR(100) | True | None |  |
| `idempotency_key` | VARCHAR(150) | True | None |  |
| `input_payload` | JSONB | False | '<callable>' |  |
| `output_payload` | JSONB | True | None |  |
| `status` | VARCHAR(24) | False | 'CREATED' |  |
| `decision` | VARCHAR(24) | True | None |  |
| `risk_score` | INTEGER | True | None |  |
| `priority` | VARCHAR(20) | False | 'NORMAL' |  |
| `queued_at` | DATETIME | True | None |  |
| `started_at` | DATETIME | True | None |  |
| `completed_at` | DATETIME | True | None |  |
| `duration_ms` | INTEGER | True | None |  |
| `attempt_count` | INTEGER | False | 0 |  |
| `cancel_requested` | BOOLEAN | False | False |  |
| `error_code` | VARCHAR(50) | True | None |  |
| `error_message` | TEXT | True | None |  |
| `model_usage` | JSONB | True | None |  |
| `tool_usage` | JSONB | True | None |  |
| `cost` | NUMERIC(12, 6) | False | 0 |  |
| `prompt_tokens` | INTEGER | True | None |  |
| `completion_tokens` | INTEGER | True | None |  |
| `total_tokens` | INTEGER | True | None |  |
| `token_accounting_complete` | BOOLEAN | False | True |  |
| `cost_amount` | NUMERIC(18, 8) | True | None |  |
| `cost_currency` | VARCHAR(3) | False | 'USD' |  |
| `pricing_version` | VARCHAR(32) | True | None |  |
| `cost_is_estimated` | BOOLEAN | False | False |  |
| `time_to_first_token_ms` | INTEGER | True | None |  |
| `generation_duration_ms` | INTEGER | True | None |  |
| `finish_reason` | VARCHAR(32) | True | None |  |
| `was_streamed` | BOOLEAN | False | False |  |
| `stream_interrupted` | BOOLEAN | False | False |  |
| `loop_iterations` | INTEGER | False | 0 |  |
| `termination_reason` | VARCHAR(40) | True | None |  |
| `created_at` | DATETIME | False | None |  |
| `updated_at` | DATETIME | False | None |  |
| `id` | UUID | False | '<callable>' |  |

### `runtime_governance_decisions` (13 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `organization_id` | UUID | False | None | organizations.id |
| `execution_id` | UUID | False | None | agent_executions.id |
| `trace_id` | VARCHAR(100) | True | None |  |
| `checkpoint` | VARCHAR(32) | False | None |  |
| `decision` | VARCHAR(12) | False | None |  |
| `reason_code` | VARCHAR(48) | False | None |  |
| `reason` | TEXT | True | None |  |
| `obligation` | JSONB | True | None |  |
| `policy_id` | UUID | True | None | runtime_governance_policies.id |
| `budget_id` | UUID | True | None | budgets.id |
| `iteration` | INTEGER | True | None |  |
| `evaluated_at` | DATETIME | False | None |  |
| `id` | UUID | False | '<callable>' |  |

### `agent_ownership_history` (11 columns)
| column | type | nullable | default | fk |
|---|---|---|---|---|
| `agent_id` | UUID | False | None | agents.id |
| `owner_role` | VARCHAR(30) | False | None |  |
| `previous_owner_type` | VARCHAR(30) | True | None |  |
| `previous_owner_id` | UUID | True | None |  |
| `new_owner_type` | VARCHAR(30) | False | None |  |
| `new_owner_id` | UUID | False | None |  |
| `reason` | TEXT | False | None |  |
| `changed_by` | UUID | False | None |  |
| `approved_by` | UUID | True | None |  |
| `changed_at` | DATETIME | False | None |  |
| `id` | UUID | False | '<callable>' |  |

## Gap re-verification (evidence with file:line)

### F6-1 — threat detection keys off ACT-run execution signals; gateway-enforced agents' denials (external_gateway_calls) are never read by any threat rule
- `threat_rules_reading_execution_tables`: 12 hit(s)
    - `app/threat/rules.py:34` `from app.models.runtime import AgentExecution, BehavioralFinding, RuntimeGovernanceDecision, ToolCall`
    - `app/threat/rules.py:95` `select(func.count(RuntimeGovernanceDecision.id))`
    - `app/threat/rules.py:96` `.join(AgentExecution, AgentExecution.id == RuntimeGovernanceDecision.execution_id)`
    - `app/threat/rules.py:98` `AgentExecution.organization_id == self.organization_id,`
    - `app/threat/rules.py:99` `AgentExecution.agent_id == self.agent.id,`
    - `app/threat/rules.py:100` `RuntimeGovernanceDecision.decision.in_(("STOP", "DENY")),`
    - `app/threat/rules.py:101` `RuntimeGovernanceDecision.evaluated_at >= self.window_start,`
    - `app/threat/rules.py:108` `def egress_denied_tool_calls(self) -> list[ToolCall]:`
- `threat_package_reading_gateway_calls`: **0 hits**
- `gateway_records_written_at`: 1 hit(s)
    - `app/bridge/gateway.py:180` `record = ExternalGatewayCall(`

### I-1 — no table/model represents an agent's runtime memory or context state (the first scan pattern also matched `RequestContextMiddleware`, an HTTP middleware, and was tightened to ORM models and memory-state columns)
- `memory_or_context_models`: **0 hits**
- `nearest_related_field_not_a_state_model`: 1 hit(s)
    - `app/models/runtime.py:68` `memory_requirements: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)`

### I-2 — AGENT_DELEGATES_TO is declared but no code path creates such an edge (no producer, no ingestion)
- `references_outside_models`: 4 hit(s)
    - `app/graph/service.py:11` `never invents an agent->agent delegation -- ``AGENT_DELEGATES_TO`` has no`
    - `app/graph/traversal.py:37` `_DELEGATION_EDGE_TYPES = ("DELEGATES_TO", "AGENT_DELEGATES_TO")`
    - `app/graph/traversal.py:420` `"""Recursive walk *backwards* over DELEGATES_TO / AGENT_DELEGATES_TO edges`
    - `app/graph/traversal.py:430` `AND edge_type IN ('DELEGATES_TO', 'AGENT_DELEGATES_TO')`
- `edge_creation_with_agent_delegates_to`: **0 hits**

### F-2 — authority-chain reconstruction starts from agent_executions; external agents produce none
- `reconstruct_reads_executions`: 5 hit(s)
    - `app/graph/traversal.py:390` `FROM agent_executions`
    - `app/graph/traversal.py:413` `def _delegation_prefix(`
    - `app/graph/traversal.py:485` `def reconstruct_authority_chain(`
    - `app/graph/traversal.py:501` `FROM agent_executions`
    - `app/graph/traversal.py:522` `"SELECT trigger_type, triggered_by_identity_id FROM agent_executions "`

### V9-1 — reachability CTE uses a path-array cycle guard (enumerates simple paths; exponential on branching graphs); default depth 16, cap 32
- `path_array_guard`: 4 hit(s)
    - `app/graph/traversal.py:34` `MAX_TRAVERSAL_DEPTH = 32`
    - `app/graph/traversal.py:35` `DEFAULT_TRAVERSAL_DEPTH = 16`
    - `app/graph/traversal.py:95` `r.path || ({step_type} || ':' || {step_id})`
    - `app/graph/traversal.py:105` `AND NOT (({step_type} || ':' || {step_id}) = ANY(r.path))`

