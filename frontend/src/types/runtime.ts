// Agent Runtime & Lifecycle Management types (Phase 5.0 §66).
import type { ID } from './common'
import type { RiskLevel } from './governance'

export type AgentLifecycleStatus =
  | 'DRAFT' | 'VALIDATING' | 'VALIDATED' | 'APPROVED' | 'ACTIVE'
  | 'SUSPENDED' | 'DEPRECATED' | 'ARCHIVED' | 'RETIRED'
export type Criticality = 'LOW' | 'MEDIUM' | 'HIGH' | 'MISSION_CRITICAL'
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
  entrypoint_type: string
  entrypoint: string
  system_instructions: string | null
  configuration_schema: Record<string, unknown> | null
  input_schema: Record<string, unknown> | null
  output_schema: Record<string, unknown> | null
  metadata: Record<string, unknown> | null
  created_at: string
}

export interface RuntimeAgent {
  id: ID
  organization_id: ID
  name: string
  slug: string | null
  description: string | null
  agent_type: string
  status: string
  lifecycle_status: AgentLifecycleStatus
  criticality: Criticality
  data_classification: string
  default_environment: RuntimeEnvironment
  project_id: ID | null
  owner_type: string | null
  owner_id: ID | null
  created_at: string
  updated_at: string
  archived_at: string | null
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
