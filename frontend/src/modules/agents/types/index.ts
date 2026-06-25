import type { ID, ISODateString } from '@/types'

export type AgentStatus = 'ACTIVE' | 'INACTIVE' | 'SUSPENDED' | 'ARCHIVED' | 'BLOCKED'
export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
export type AgentHealth = 'HEALTHY' | 'WARNING' | 'OFFLINE'

/** Capability flags an agent can be granted (Create wizard, step 2). */
export type AgentCapability =
  | 'read'
  | 'write'
  | 'execute'
  | 'delete'
  | 'external_api'
  | 'database'

/** Full agent record (matches the backend AgentRead schema). */
export interface Agent {
  id: ID
  organization_id: ID
  name: string
  description: string | null
  agent_type: string
  status: AgentStatus
  owner: string | null
  department: string | null
  version: string
  capabilities: string[]
  default_risk_score: number
  max_allowed_risk: number
  human_approval_required: boolean
  auto_suspend_threshold: number | null
  risk_level: RiskLevel
  health: AgentHealth
  created_at: ISODateString
  updated_at: ISODateString
}

/** Paginated list envelope (GET /agents). */
export interface AgentListResponse {
  items: Agent[]
  total: number
  page: number
  page_size: number
}

/** Per-agent operational statistics (GET /agents/{id}/stats). */
export interface AgentStats {
  actions_today: number
  total_actions: number
  blocked_actions: number
  pending_approvals: number
  policies_triggered: number
  average_risk: number
  success_rate: number
}

export type AgentSortField =
  | 'name'
  | 'agent_type'
  | 'status'
  | 'risk_level'
  | 'version'
  | 'created_at'
  | 'updated_at'

/** Query params for the server-driven agents table. */
export interface AgentListParams {
  search?: string
  status?: AgentStatus
  agent_type?: string
  risk_level?: RiskLevel
  sort_by?: AgentSortField
  sort_dir?: 'asc' | 'desc'
  page: number
  page_size: number
}

export interface AgentCreateInput {
  name: string
  description?: string | null
  agent_type: string
  owner?: string | null
  department?: string | null
  version?: string
  capabilities?: string[]
  default_risk_score?: number
  max_allowed_risk?: number
  human_approval_required?: boolean
  auto_suspend_threshold?: number | null
  risk_level?: RiskLevel
}

export type AgentUpdateInput = Partial<AgentCreateInput> & { status?: AgentStatus }

/** Returned once on creation — includes the plaintext API key. */
export interface AgentCreateResponse extends Agent {
  api_key: string
}
