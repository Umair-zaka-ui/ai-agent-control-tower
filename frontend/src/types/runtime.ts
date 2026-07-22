// Agent Runtime & Lifecycle Management types (Phase 5.0 §66).
import type { ID } from './common'
import type { RiskLevel } from './governance'

// Phase 5.1 §20 — the full 13-state registry lifecycle (supersedes the
// Phase 5.0 8-state version, which had no REGISTERED/PENDING_APPROVAL/
// REJECTED/VALIDATION_FAILED gate).
export type AgentLifecycleStatus =
  | 'DRAFT' | 'REGISTERED' | 'VALIDATING' | 'VALIDATION_FAILED' | 'VALIDATED'
  | 'PENDING_APPROVAL' | 'REJECTED' | 'APPROVED' | 'ACTIVE'
  | 'SUSPENDED' | 'DEPRECATED' | 'ARCHIVED' | 'RETIRED'
export type Criticality = 'LOW' | 'MEDIUM' | 'HIGH' | 'MISSION_CRITICAL'
export type AutonomyLevel =
  | 'ASSISTIVE' | 'SUPERVISED' | 'SEMI_AUTONOMOUS' | 'AUTONOMOUS' | 'CRITICAL_AUTONOMOUS'
export type DataClassification = 'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'RESTRICTED' | 'REGULATED'
export type OwnerRole = 'BUSINESS_OWNER' | 'TECHNICAL_OWNER' | 'COMPLIANCE_OWNER' | 'SECURITY_OWNER' | 'DATA_OWNER'
export type RuntimeEnvironment = 'DEVELOPMENT' | 'TEST' | 'STAGING' | 'PRODUCTION' | 'SANDBOX'
export type VersionStatus =
  | 'DRAFT' | 'VALIDATING' | 'READY_FOR_REVIEW' | 'APPROVED' | 'PUBLISHED' | 'DEPRECATED' | 'REVOKED'
export type DeploymentStatus =
  | 'CREATED' | 'PENDING_APPROVAL' | 'SCHEDULED' | 'DEPLOYING' | 'HEALTH_CHECKING'
  | 'ACTIVE' | 'DEGRADED' | 'FAILED' | 'SUSPENDED' | 'ROLLING_BACK' | 'RETIRED'
export type ExecutionStatus =
  | 'CREATED' | 'AUTHORIZING' | 'DENIED' | 'PENDING_APPROVAL' | 'REJECTED' | 'QUEUED' | 'SCHEDULED'
  | 'RUNNING' | 'BLOCKED' | 'SUCCEEDED' | 'FAILED' | 'TIMED_OUT' | 'CANCELLED' | 'DEAD_LETTERED'
export type Priority = 'LOW' | 'NORMAL' | 'HIGH' | 'CRITICAL'

export interface AgentDefinition {
  id: ID
  agent_id: ID
  name: string
  description: string | null
  framework: string
  framework_version: string | null
  entrypoint_type: string
  entrypoint: string
  runtime_language: string | null
  system_instructions: string | null
  configuration_schema: Record<string, unknown> | null
  input_schema: Record<string, unknown> | null
  output_schema: Record<string, unknown> | null
  capability_declarations: string[]
  tool_declarations: string[]
  model_requirements: Record<string, unknown>
  memory_requirements: Record<string, unknown>
  data_requirements: Record<string, unknown>
  network_requirements: Record<string, unknown>
  secret_requirements: Record<string, unknown>
  runtime_requirements: Record<string, unknown>
  metadata: Record<string, unknown> | null
  created_at: string
}

export interface RuntimeAgent {
  id: ID
  organization_id: ID
  name: string
  display_name: string | null
  slug: string | null
  description: string | null
  business_purpose: string | null
  agent_type: string
  status: string
  lifecycle_status: AgentLifecycleStatus
  criticality: Criticality
  risk_level: string
  data_classification: string
  autonomy_level: AutonomyLevel
  default_environment: RuntimeEnvironment
  project_id: ID | null
  business_unit_id: ID | null
  department_id: ID | null
  team_id: ID | null
  identity_id: ID | null
  owner_type: string | null
  owner_id: ID | null
  technical_owner_id: ID | null
  compliance_owner_id: ID | null
  support_contact: string | null
  documentation_url: string | null
  repository_url: string | null
  tags: string[]
  metadata: Record<string, unknown>
  registration_source: string
  external_reference: string | null
  created_by: ID | null
  updated_by: ID | null
  row_version: number
  created_at: string
  updated_at: string
  validated_at: string | null
  approved_at: string | null
  activated_at: string | null
  suspended_at: string | null
  archived_at: string | null
  retired_at: string | null
}

export interface AgentOwnershipHistoryEntry {
  id: ID
  agent_id: ID
  owner_role: OwnerRole
  previous_owner_type: string | null
  previous_owner_id: ID | null
  new_owner_type: string
  new_owner_id: ID
  reason: string
  changed_by: ID
  approved_by: ID | null
  changed_at: string
}

export interface AgentIdentityRecord {
  id: ID
  agent_id: ID
  client_id: string
  credential_type: string
  status: string
  last_used_at: string | null
  expires_at: string | null
}

export interface ValidationFinding {
  code: string
  field: string | null
  message: string
  severity: 'INFO' | 'WARNING' | 'ERROR' | 'BLOCKING'
}

export interface ValidationRun {
  id: ID
  agent_id: ID
  status: 'RUNNING' | 'PASSED' | 'FAILED'
  validator_version: string
  summary: { passed: number; warnings: number; failed: number }
  errors: ValidationFinding[]
  warnings: ValidationFinding[]
  checks: { name: string; passed: boolean }[]
  started_at: string
  completed_at: string | null
  created_by: ID | null
  created_at: string
}

export type DuplicateOutcome = 'POSSIBLE_DUPLICATE' | 'LIKELY_DUPLICATE' | 'CONFIRMED_DUPLICATE'
export type DuplicateReviewDecision =
  | 'CONFIRM_DUPLICATE' | 'NOT_DUPLICATE' | 'MERGE_REQUIRED' | 'JUSTIFIED_SEPARATE_AGENT'

export interface DuplicateMatch {
  id: ID
  source_agent_id: ID
  candidate_agent_id: ID
  match_type: 'EXACT' | 'SIMILAR'
  confidence_score: number
  matching_fields: string[]
  status: DuplicateOutcome
  reviewed_by: ID | null
  review_decision: DuplicateReviewDecision | null
  review_reason: string | null
  created_at: string
  reviewed_at: string | null
}

export interface ImportJob {
  id: ID
  organization_id: ID
  file_name: string
  format: 'JSON' | 'YAML' | 'CSV'
  mode: 'CREATE_ONLY' | 'UPDATE_DRAFTS' | 'UPSERT_NON_ACTIVE' | 'VALIDATE_ONLY'
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED'
  total_records: number
  successful_records: number
  failed_records: number
  warning_records: number
  created_by: ID | null
  started_at: string | null
  completed_at: string | null
  created_at: string
}

export interface ImportItem {
  id: ID
  import_job_id: ID
  record_identifier: string
  status: 'CREATED' | 'UPDATED' | 'SKIPPED' | 'FAILED'
  agent_id: ID | null
  errors: { code: string; message: string }[]
  warnings: { code: string; message: string }[]
  created_at: string
}

export type ExportType = 'FULL_CONFIGURATION' | 'INVENTORY_SUMMARY' | 'COMPLIANCE_REPORT' | 'MIGRATION_PACKAGE'

export interface ExportJob {
  id: ID
  organization_id: ID
  export_type: ExportType
  format: 'JSON' | 'YAML' | 'CSV'
  filters: Record<string, unknown>
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED'
  record_count: number
  storage_reference: string | null
  expires_at: string | null
  created_by: ID | null
  created_at: string
  completed_at: string | null
}

export interface MigrationRecord {
  id: ID
  agent_id: ID
  migration_batch_id: string
  legacy_source: string
  legacy_id: string
  migration_status: string
  mapping_warnings: string[]
  migrated_by: ID | null
  migrated_at: string
}

export interface AgentLifecycleEventEntry {
  id: ID
  agent_id: ID
  organization_id: ID
  previous_status: string | null
  new_status: string
  reason: string | null
  requested_by: ID
  approved_by: ID | null
  authorization_decision_id: ID | null
  request_id: string
  correlation_id: string
  metadata: Record<string, unknown>
  created_at: string
}

export interface AgentVersion {
  id: ID
  agent_id: ID
  definition_id: ID
  version: number
  semantic_version: string
  status: VersionStatus
  configuration_snapshot: Record<string, unknown>
  prompt_snapshot: Record<string, unknown> | null
  model_configuration: Record<string, unknown>
  capabilities_snapshot: string[]
  tools_snapshot: string[]
  policy_snapshot: Record<string, unknown> | null
  checksum: string
  release_notes: string | null
  created_by: ID | null
  created_at: string
  published_at: string | null
  deprecated_at: string | null
}

export interface Deployment {
  id: ID
  agent_id: ID
  agent_version_id: ID
  organization_id: ID
  environment: RuntimeEnvironment
  deployment_strategy: string
  status: DeploymentStatus
  desired_replicas: number
  active_replicas: number
  configuration: Record<string, unknown>
  runtime_limits: Record<string, unknown>
  health_status: string
  deployed_by: ID | null
  deployed_at: string | null
  updated_at: string
  retired_at: string | null
}

export interface DeploymentHealth {
  id: ID
  deployment_id: ID
  worker_id: string | null
  status: string
  metrics: Record<string, unknown> | null
  checked_at: string
}

export interface AgentExecution {
  id: ID
  organization_id: ID
  agent_id: ID
  agent_version_id: ID
  deployment_id: ID | null
  trigger_type: string
  triggered_by_identity_id: ID | null
  parent_execution_id: ID | null
  correlation_id: string | null
  idempotency_key: string | null
  input_payload: Record<string, unknown>
  output_payload: Record<string, unknown> | null
  status: ExecutionStatus
  decision: string | null
  risk_score: number | null
  priority: Priority
  queued_at: string | null
  started_at: string | null
  completed_at: string | null
  duration_ms: number | null
  attempt_count: number
  cancel_requested: boolean
  error_code: string | null
  error_message: string | null
  model_usage: Record<string, unknown> | null
  tool_usage: Record<string, unknown> | null
  cost: number
  created_at: string
  updated_at: string
}

export interface ExecutionAttempt {
  id: ID
  execution_id: ID
  attempt_number: number
  worker_id: string | null
  status: string
  started_at: string | null
  completed_at: string | null
  duration_ms: number | null
  error_code: string | null
  error_message: string | null
  created_at: string
}

export interface ToolCall {
  id: ID
  execution_id: ID
  agent_id: ID
  tool_id: ID
  action: string
  input_summary: Record<string, unknown> | null
  output_summary: Record<string, unknown> | null
  status: string
  risk_score: number | null
  started_at: string | null
  completed_at: string | null
  duration_ms: number | null
  error_code: string | null
  cost: number | null
  created_at: string
}

export interface RuntimeEvent {
  id: ID
  organization_id: ID
  agent_id: ID | null
  deployment_id: ID | null
  execution_id: ID | null
  event_type: string
  severity: string
  payload: Record<string, unknown> | null
  created_at: string
}

export interface Capability {
  id: ID
  name: string
  display_name: string
  description: string | null
  category: string | null
  risk_level: RiskLevel
  requires_approval: boolean
  required_permissions: string[]
  prohibited_environments: string[]
  created_at: string
  updated_at: string
}

export interface AgentCapability {
  id: ID
  agent_id: ID
  agent_version_id: ID | null
  capability_id: ID
  status: string
  constraints: Record<string, unknown> | null
  approved_by: ID | null
  approved_at: string | null
  expires_at: string | null
  created_at: string
}

export interface RuntimeTool {
  id: ID
  organization_id: ID | null
  name: string
  display_name: string
  description: string | null
  tool_type: string
  endpoint_reference: string | null
  risk_level: RiskLevel
  side_effect_level: string
  data_classification: string
  requires_approval: boolean
  timeout_seconds: number
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface AgentTool {
  id: ID
  agent_id: ID
  agent_version_id: ID | null
  tool_id: ID
  allowed_actions: string[]
  constraints: Record<string, unknown> | null
  environment: string | null
  status: string
  approved_by: ID | null
  approved_at: string | null
  expires_at: string | null
  created_at: string
}

export interface RuntimeApproval {
  id: ID
  organization_id: ID
  agent_id: ID | null
  agent_version_id: ID | null
  deployment_id: ID | null
  execution_id: ID | null
  requested_action: string
  risk_score: number | null
  reason: string | null
  matched_policies: unknown[]
  request_summary: Record<string, unknown> | null
  status: string
  requested_by: ID | null
  reviewed_by: ID | null
  decision_comment: string | null
  expires_at: string | null
  created_at: string
  reviewed_at: string | null
}

export interface RuntimeDashboard {
  registered_agents: number
  active_agents: number
  active_deployments: number
  running_executions: number
  queued_executions: number
  failed_executions_24h: number
  pending_approvals: number
  suspended_agents: number
  cost_today: number
  success_rate: number
  avg_queue_ms: number
  avg_execution_ms: number
  execution_trend: { date: string; count: number }[]
  status_distribution: { status: string; count: number }[]
}

export interface WorkerStatus {
  worker_id: string
  last_seen: string | null
  status: string
}
