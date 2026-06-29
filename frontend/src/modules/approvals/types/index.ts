import type { ID, ISODateString, JsonObject } from '@/types'

/** Approval lifecycle state (mirrors the backend ApprovalDecision enum). */
export type ApprovalStatus = 'PENDING' | 'APPROVED' | 'REJECTED' | 'ESCALATED' | 'EXPIRED'
export type ApprovalPriority = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
export type EscalationTarget = 'REVIEWER' | 'MANAGER' | 'COMPLIANCE_OFFICER' | 'SECURITY_TEAM'

/** A row in the approval queue / history table (ApprovalListItem). */
export interface ApprovalListItem {
  id: ID
  agent_action_id: ID
  requested_by_agent_id: ID
  agent_name: string | null
  resource: string
  action: string
  risk_score: number
  decision: ApprovalStatus
  priority: ApprovalPriority
  escalation_target: string | null
  reviewer_name: string | null
  assigned_to_name: string | null
  sla_due_at: ISODateString | null
  created_at: ISODateString
  reviewed_at: ISODateString | null
}

export interface ApprovalComment {
  id: ID
  approval_id: ID
  user_id: ID | null
  comment: string
  created_at: ISODateString
}

export interface ApprovalAgentInfo {
  id: ID
  name: string
  version: string | null
  owner: string | null
  department: string | null
  status: string | null
  health: string | null
  last_activity: ISODateString | null
}

export interface ApprovalActionInfo {
  id: ID
  resource: string
  action: string
  input_payload: JsonObject
  risk_score: number
  decision: string
  decision_reason: string
  status: string
  created_at: ISODateString
}

export interface ApprovalPolicyInfo {
  matched: boolean
  policy_name: string | null
  decision: string | null
  conditions: JsonObject
  reason: string | null
}

export interface ApprovalRiskAssessment {
  score: number
  action_score: number
  resource_score: number
  factors: Record<string, number>
  confidence: number
  recommendation: string
}

/** Full detail payload for the review workbench (ApprovalDetail). */
export interface ApprovalDetail {
  id: ID
  organization_id: ID
  agent_action_id: ID
  requested_by_agent_id: ID
  reviewed_by_user_id: ID | null
  assigned_to_user_id: ID | null
  decision: ApprovalStatus
  priority: ApprovalPriority
  review_comment: string | null
  escalation_target: string | null
  sla_due_at: ISODateString | null
  escalated_at: ISODateString | null
  created_at: ISODateString
  reviewed_at: ISODateString | null
  reviewer_name: string | null
  assigned_to_name: string | null
  agent: ApprovalAgentInfo | null
  action: ApprovalActionInfo | null
  policy: ApprovalPolicyInfo
  risk: ApprovalRiskAssessment
  comments: ApprovalComment[]
}

export interface ApprovalTimelineEvent {
  id: ID
  event_type: string
  actor_type: string
  actor_id: ID | null
  actor_name: string | null
  metadata: JsonObject
  created_at: ISODateString
}

export interface ApprovalStatistics {
  pending: number
  approved_today: number
  rejected_today: number
  escalated: number
  avg_review_seconds: number | null
}

export interface ApprovalListParams {
  status?: ApprovalStatus
  priority?: ApprovalPriority
  risk_min?: number
  risk_max?: number
  search?: string
}

export interface ReviewInput {
  review_comment?: string
}

export interface EscalateInput {
  target: EscalationTarget
  reason: string
  assigned_to_user_id?: ID
}

export interface AssignInput {
  user_id: ID
}
