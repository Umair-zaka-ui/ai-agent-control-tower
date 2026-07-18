// Identity Governance & Administration types (Phase 4.3.8 §19).
import type { ID } from './common'

export type GovCampaignStatus = 'DRAFT' | 'SCHEDULED' | 'ACTIVE' | 'COMPLETED' | 'ARCHIVED'
export type GovCampaignType = 'QUARTERLY' | 'ANNUAL' | 'PRIVILEGED' | 'PROJECT' | 'EMERGENCY'
export type GovReviewDecision = 'PENDING' | 'CERTIFIED' | 'REVOKED' | 'MODIFIED' | 'DELEGATED'

export interface GovCampaign {
  id: ID
  organization_id: ID
  name: string
  description: string | null
  campaign_type: GovCampaignType
  status: GovCampaignStatus
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

export interface GovReviewItem {
  id: ID
  campaign_id: ID
  subject_id: ID
  subject_label: string
  assignment_id: ID | null
  role_id: ID | null
  role_name: string
  scope_label: string | null
  decision: GovReviewDecision
  decided_by: ID | null
  decided_at: string | null
  comment: string | null
}

export type RuleType = 'SOD' | 'TOXIC_PERMISSION'
export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
export type RuleStatus = 'DRAFT' | 'ACTIVE' | 'DISABLED'

export interface SoDRule {
  id: ID
  organization_id: ID
  rule_type: RuleType
  name: string
  description: string | null
  risk_level: RiskLevel
  permissions_a: string[]
  permissions_b: string[]
  scope: Record<string, unknown> | null
  status: RuleStatus
  created_by: ID | null
  approved_by: ID | null
  approved_at: string | null
  created_at: string
  updated_at: string
}

export type FindingType = 'SOD_VIOLATION' | 'TOXIC_PERMISSION' | 'ORPHANED_ACCOUNT' | 'PRIVILEGED_REVIEW_DUE'
export type FindingStatus = 'OPEN' | 'ACKNOWLEDGED' | 'REMEDIATED' | 'DISMISSED'

export interface GovernanceFinding {
  id: ID
  organization_id: ID
  finding_type: FindingType
  severity: RiskLevel
  identity_id: ID | null
  identity_label: string | null
  resource_id: ID | null
  rule_id: ID | null
  details: Record<string, unknown> | null
  status: FindingStatus
  detected_at: string
  resolved_at: string | null
  resolved_by: ID | null
}

export type RemediationActionType =
  | 'REMOVE_ROLE' | 'DISABLE_ACCOUNT' | 'DISABLE_API_KEY' | 'EXPIRE_DELEGATION'
  | 'NOTIFY_MANAGER' | 'CREATE_APPROVAL_REQUEST' | 'REQUIRE_MFA' | 'CREATE_SECURITY_TICKET'
export type RemediationStatus = 'PENDING' | 'APPROVED' | 'EXECUTED' | 'FAILED' | 'CANCELLED'
export type RemediationMode = 'MANUAL' | 'APPROVAL' | 'AUTOMATIC'

export interface RemediationAction {
  id: ID
  organization_id: ID
  finding_id: ID
  action_type: RemediationActionType
  status: RemediationStatus
  mode: RemediationMode
  payload: Record<string, unknown> | null
  created_by: ID | null
  approved_by: ID | null
  executed_by: ID | null
  executed_at: string | null
  created_at: string
}

export interface GovernanceRiskScore {
  id: ID
  identity_id: ID
  identity_label: string
  score: number
  band: RiskLevel | 'LOW'
  factors: Record<string, unknown> | null
  computed_at: string
}

export interface PrivilegedAccount {
  identity_id: ID
  identity_label: string
  role_name: string
  assignment_id: ID | null
  risk_score: number
  risk_band: string
  last_activity_at: string | null
  review_status: string | null
  review_due_at: string | null
}

export interface PrivilegedReview {
  id: ID
  identity_id: ID
  identity_label: string
  role_name: string
  risk_score: number | null
  status: 'PENDING' | 'APPROVED' | 'REVOKED'
  reviewed_by: ID | null
  reviewed_at: string | null
  due_at: string | null
  created_at: string
}

export interface OrphanedScanResult {
  scanned_users: number
  scanned_api_keys: number
  scanned_roles: number
  findings_created: number
}

export type ComplianceFramework = 'SOC2' | 'ISO27001' | 'HIPAA' | 'GDPR' | 'NIST' | 'CIS' | 'INTERNAL'

export interface ComplianceFrameworkInfo {
  framework: ComplianceFramework
  display_name: string
  controls: { control: string; platform_evidence: string }[]
}

export interface ComplianceReport {
  id: ID
  organization_id: ID
  framework: ComplianceFramework
  report_type: string
  scope: Record<string, unknown> | null
  payload: Record<string, unknown>
  version: string
  generated_by: ID | null
  generated_at: string
}

export interface GovernanceDashboard {
  widgets: {
    active_campaigns: number
    pending_reviews: number
    overdue_reviews: number
    privileged_accounts: number
    toxic_permission_findings: number
    sod_findings: number
    orphaned_accounts: number
    compliance_status: string
    remediation_queue: number
    governance_risk_distribution: Record<string, number>
  }
  charts: GovernanceAnalytics
}

export interface GovernanceAnalytics {
  review_completion_trend: { date: string; completed: number }[]
  findings_by_severity: { severity: string; total: number }[]
  findings_by_type: { finding_type: string; total: number }[]
  privileged_access_growth: { month: string; total: number }[]
  risk_score_distribution: { band: string; total: number }[]
}
