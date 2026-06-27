import type { ID, ISODateString, JsonObject } from '@/types'

export type PolicyDecision = 'ALLOW' | 'BLOCK' | 'PENDING_APPROVAL'
export type PolicySeverity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
export type PolicyStatus = 'DRAFT' | 'ENABLED' | 'DISABLED' | 'ARCHIVED'

/** Full policy record (matches the backend PolicyRead schema). */
export interface Policy {
  id: ID
  organization_id: ID
  name: string
  description: string | null
  resource: string
  action: string
  conditions: JsonObject
  decision: PolicyDecision
  priority: number
  enabled: boolean
  severity: PolicySeverity
  status: PolicyStatus
  trigger_count: number
  last_triggered_at: ISODateString | null
  created_by: ID | null
  created_at: ISODateString
  updated_at: ISODateString
}

export interface PolicyTemplate {
  key: string
  name: string
  description: string
  resource: string
  action: string
  conditions: JsonObject
  decision: PolicyDecision
  severity: PolicySeverity
}

export interface PolicyTestRequest {
  agent_id?: ID
  resource: string
  action: string
  input_payload: JsonObject
}

export interface PolicyTestResult {
  matched: boolean
  decision: PolicyDecision | null
  reason: string
  risk_score: number
  triggered_conditions: string[]
  explanation: string
}

export interface PolicyListParams {
  search?: string
  resource?: string
  action?: string
  decision?: PolicyDecision
  severity?: PolicySeverity
  status?: PolicyStatus
}

export interface PolicyCreateInput {
  name: string
  description?: string | null
  resource: string
  action: string
  conditions: JsonObject
  decision: PolicyDecision
  priority?: number
  severity?: PolicySeverity
  status?: PolicyStatus
}

export type PolicyUpdateInput = Partial<PolicyCreateInput>
