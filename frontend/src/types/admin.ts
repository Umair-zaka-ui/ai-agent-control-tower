// Administration portal types (Phase 4.3.7 §18).
import type { ID } from './common'

export interface AdminDashboardWidgets {
  total_users: number
  active_roles: number
  active_permissions: number
  active_policies: number
  active_sessions: number
  authorization_requests_24h: number
  denied_requests_24h: number
  approval_requests_pending: number
  mfa_challenges_total: number
  high_risk_decisions_24h: number
  cache_hit_ratio: number
  policy_evaluation_latency_ms: number
}

export interface AdminDashboard {
  widgets: AdminDashboardWidgets
  charts: {
    authorization_trend: { date: string; total: number; denied: number }[]
    top_permissions: { permission: string; total: number; denied: number }[]
    policy_matches: { policy: string; matches: number }[]
    decision_breakdown: { decision: string; total: number }[]
    approval_queue: { status: string; total: number }[]
  }
}

export interface AuthorizationDecisionRow {
  id: ID
  identity_id: ID | null
  organization_id: ID | null
  permission: string
  resource_type: string | null
  resource_id: ID | null
  allowed: boolean
  reason: string | null
  scope: string | null
  source_role: string | null
  evaluation_time_ms: number | null
  request_id: string | null
  created_at: string
}

export type CampaignStatus = 'DRAFT' | 'SCHEDULED' | 'ACTIVE' | 'COMPLETED' | 'ARCHIVED'

export interface AccessReviewCampaign {
  id: ID
  organization_id: ID
  name: string
  description: string | null
  status: CampaignStatus
  scope: Record<string, unknown> | null
  reviewer_id: ID | null
  due_at: string | null
  created_by: ID | null
  activated_at: string | null
  completed_at: string | null
  created_at: string
  total_items: number
  decided_items: number
  revoked_items: number
}

export interface AccessReviewItem {
  id: ID
  campaign_id: ID
  subject_id: ID
  subject_label: string
  assignment_id: ID | null
  role_id: ID | null
  role_name: string
  scope_label: string | null
  decision: 'PENDING' | 'CERTIFIED' | 'REVOKED'
  decided_by: ID | null
  decided_at: string | null
  comment: string | null
}

export interface SecurityAnalytics {
  denied_requests_24h: number
  denied_requests_7d: number
  high_risk_decisions_24h: number
  mfa_challenges_total: number
  approval_requests_total: number
  approval_approval_rate: number
  authorization_latency_ms_avg: number
  authorization_latency_ms_p95: number
  cache_hit_ratio: number
  abac_denies_total: number
  abac_challenges_total: number
  policy_errors_total: number
  top_denied_permissions: { permission: string; denied: number }[]
  denied_trend: { date: string; denied: number }[]
  sharing_trend: { date: string; shares: number }[]
}
