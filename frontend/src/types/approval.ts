import type { ID, ISODateString } from './common'

export type ApprovalDecision = 'PENDING' | 'APPROVED' | 'REJECTED'
export type ApprovalPriority = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

/** Approval record (matches the backend ApprovalRead schema). */
export interface Approval {
  id: ID
  organization_id: ID
  agent_action_id: ID
  requested_by_agent_id: ID
  reviewed_by_user_id?: ID | null
  decision: ApprovalDecision
  priority: ApprovalPriority
  review_comment?: string | null
  sla_due_at?: ISODateString | null
  created_at: ISODateString
  reviewed_at?: ISODateString | null
}

export interface ApprovalComment {
  id: ID
  approval_id: ID
  user_id?: ID | null
  comment: string
  created_at: ISODateString
}

export interface ApprovalDecisionInput {
  review_comment?: string
}
