import type { ID, ISODateString } from './common'

export type ApprovalStatus = 'PENDING' | 'APPROVED' | 'REJECTED'
export type ApprovalPriority = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export interface Approval {
  id: ID
  agent_action_id: ID
  status: ApprovalStatus
  priority: ApprovalPriority
  risk_score: number
  sla_due_at?: ISODateString | null
  reviewer_id?: ID | null
  review_comment?: string | null
  created_at: ISODateString
  decided_at?: ISODateString | null
}

export interface ApprovalComment {
  id: ID
  approval_id: ID
  author_id: ID
  body: string
  created_at: ISODateString
}

export interface ApprovalDecisionInput {
  review_comment?: string
}
