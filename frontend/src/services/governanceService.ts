import type {
  ComplianceFrameworkInfo,
  ComplianceReport,
  GovCampaign,
  GovCampaignType,
  GovernanceAnalytics,
  GovernanceDashboard,
  GovernanceFinding,
  GovernanceRiskScore,
  GovReviewItem,
  ID,
  OrphanedScanResult,
  PrivilegedAccount,
  PrivilegedReview,
  RemediationAction,
  RemediationActionType,
  RemediationMode,
  RuleType,
  SoDRule,
} from '@/types'
import { apiClient } from './apiClient'

const BASE = '/api/v1/governance'

/**
 * Identity Governance & Administration API (Phase 4.3.8 §19, mounted at
 * /api/v1/governance). Every call is re-authorized server-side against the
 * governance.* permission set; all mutations are audited.
 */
export const governanceService = {
  // --- Dashboard / analytics (§21, §26) --- //
  async dashboard(): Promise<GovernanceDashboard> {
    const { data } = await apiClient.get<GovernanceDashboard>(`${BASE}/dashboard`)
    return data
  },
  async analytics(): Promise<GovernanceAnalytics> {
    const { data } = await apiClient.get<GovernanceAnalytics>(`${BASE}/analytics`)
    return data
  },

  // --- Certification campaigns (§5-§7) --- //
  async campaigns(status?: string): Promise<GovCampaign[]> {
    const suffix = status ? `?status=${status}` : ''
    const { data } = await apiClient.get<GovCampaign[]>(`${BASE}/campaigns${suffix}`)
    return data
  },
  async campaign(id: ID): Promise<GovCampaign> {
    const { data } = await apiClient.get<GovCampaign>(`${BASE}/campaigns/${id}`)
    return data
  },
  async createCampaign(payload: {
    name: string
    description?: string
    campaign_type?: GovCampaignType
    scope?: Record<string, unknown>
    due_at?: string
  }): Promise<GovCampaign> {
    const { data } = await apiClient.post<GovCampaign>(`${BASE}/campaigns`, payload)
    return data
  },
  async launchCampaign(id: ID): Promise<GovCampaign> {
    const { data } = await apiClient.post<GovCampaign>(`${BASE}/campaigns/${id}/launch`)
    return data
  },
  async completeCampaign(id: ID): Promise<GovCampaign> {
    const { data } = await apiClient.post<GovCampaign>(`${BASE}/campaigns/${id}/complete`)
    return data
  },
  async archiveCampaign(id: ID): Promise<GovCampaign> {
    const { data } = await apiClient.post<GovCampaign>(`${BASE}/campaigns/${id}/archive`)
    return data
  },
  async campaignItems(id: ID): Promise<GovReviewItem[]> {
    const { data } = await apiClient.get<GovReviewItem[]>(`${BASE}/campaigns/${id}/items`)
    return data
  },
  async exportCampaign(id: ID): Promise<Record<string, unknown>> {
    const { data } = await apiClient.get<Record<string, unknown>>(`${BASE}/campaigns/${id}/export`)
    return data
  },

  // --- Reviews (§7) --- //
  async approveReview(itemId: ID, comment?: string): Promise<GovReviewItem> {
    const { data } = await apiClient.post<GovReviewItem>(`${BASE}/reviews/${itemId}/approve`, { comment })
    return data
  },
  async revokeReview(itemId: ID, comment?: string): Promise<GovReviewItem> {
    const { data } = await apiClient.post<GovReviewItem>(`${BASE}/reviews/${itemId}/revoke`, { comment })
    return data
  },
  async modifyReview(itemId: ID, comment?: string): Promise<GovReviewItem> {
    const { data } = await apiClient.post<GovReviewItem>(`${BASE}/reviews/${itemId}/modify`, { comment })
    return data
  },
  async delegateReview(itemId: ID, delegateTo: ID, comment?: string): Promise<GovReviewItem> {
    const { data } = await apiClient.post<GovReviewItem>(`${BASE}/reviews/${itemId}/delegate`, {
      comment, delegate_to: delegateTo,
    })
    return data
  },

  // --- SoD rules + findings (§9) --- //
  async sodRules(status?: string): Promise<SoDRule[]> {
    const suffix = status ? `?status=${status}` : ''
    const { data } = await apiClient.get<SoDRule[]>(`${BASE}/sod-rules${suffix}`)
    return data
  },
  async createSodRule(payload: {
    name: string
    description?: string
    risk_level?: string
    permissions_a: string[]
    permissions_b: string[]
  }): Promise<SoDRule> {
    const { data } = await apiClient.post<SoDRule>(`${BASE}/sod-rules`, payload)
    return data
  },
  async activateSodRule(id: ID): Promise<SoDRule> {
    const { data } = await apiClient.post<SoDRule>(`${BASE}/sod-rules/${id}/activate`)
    return data
  },
  async disableSodRule(id: ID): Promise<SoDRule> {
    const { data } = await apiClient.post<SoDRule>(`${BASE}/sod-rules/${id}/disable`)
    return data
  },
  async sodFindings(status?: string): Promise<GovernanceFinding[]> {
    const suffix = status ? `?status=${status}` : ''
    const { data } = await apiClient.get<GovernanceFinding[]>(`${BASE}/sod-findings${suffix}`)
    return data
  },
  async scanSod(): Promise<GovernanceFinding[]> {
    const { data } = await apiClient.post<GovernanceFinding[]>(`${BASE}/sod-findings/scan`)
    return data
  },

  // --- Toxic permission rules + findings (§10) --- //
  async toxicRules(status?: string): Promise<SoDRule[]> {
    const suffix = status ? `?status=${status}` : ''
    const { data } = await apiClient.get<SoDRule[]>(`${BASE}/toxic-rules${suffix}`)
    return data
  },
  async createToxicRule(payload: {
    name: string
    description?: string
    risk_level?: string
    permissions_a: string[]
    permissions_b: string[]
  }): Promise<SoDRule> {
    const { data } = await apiClient.post<SoDRule>(`${BASE}/toxic-rules`, payload)
    return data
  },
  async activateToxicRule(id: ID): Promise<SoDRule> {
    const { data } = await apiClient.post<SoDRule>(`${BASE}/toxic-rules/${id}/activate`)
    return data
  },
  async disableToxicRule(id: ID): Promise<SoDRule> {
    const { data } = await apiClient.post<SoDRule>(`${BASE}/toxic-rules/${id}/disable`)
    return data
  },
  async toxicFindings(status?: string): Promise<GovernanceFinding[]> {
    const suffix = status ? `?status=${status}` : ''
    const { data } = await apiClient.get<GovernanceFinding[]>(`${BASE}/toxic-findings${suffix}`)
    return data
  },
  async scanToxic(): Promise<GovernanceFinding[]> {
    const { data } = await apiClient.post<GovernanceFinding[]>(`${BASE}/toxic-findings/scan`)
    return data
  },

  // --- Governance findings (§17) --- //
  async findings(filters: { finding_type?: string; status?: string; severity?: string } = {}):
      Promise<GovernanceFinding[]> {
    const q = new URLSearchParams()
    if (filters.finding_type) q.set('finding_type', filters.finding_type)
    if (filters.status) q.set('status', filters.status)
    if (filters.severity) q.set('severity', filters.severity)
    const suffix = q.toString() ? `?${q}` : ''
    const { data } = await apiClient.get<GovernanceFinding[]>(`${BASE}/findings${suffix}`)
    return data
  },
  async remediateFinding(id: ID, status: string, comment?: string): Promise<GovernanceFinding> {
    const { data } = await apiClient.post<GovernanceFinding>(`${BASE}/findings/${id}/remediate`, {
      status, comment,
    })
    return data
  },

  // --- Privileged access governance (§11) --- //
  async privilegedAccounts(): Promise<PrivilegedAccount[]> {
    const { data } = await apiClient.get<PrivilegedAccount[]>(`${BASE}/privileged-accounts`)
    return data
  },
  async requestPrivilegedReview(identityId: ID, roleName: string, assignmentId?: ID | null):
      Promise<{ id: ID; status: string; due_at: string | null }> {
    const q = new URLSearchParams({ identity_id: identityId, role_name: roleName })
    if (assignmentId) q.set('assignment_id', assignmentId)
    const { data } = await apiClient.post(`${BASE}/privileged-accounts/reviews?${q}`)
    return data
  },
  async privilegedReviews(status?: string): Promise<PrivilegedReview[]> {
    const suffix = status ? `?status=${status}` : ''
    const { data } = await apiClient.get<PrivilegedReview[]>(`${BASE}/privileged-accounts/reviews${suffix}`)
    return data
  },
  async decidePrivilegedReview(reviewId: ID, decision: 'APPROVED' | 'REVOKED', assignmentId?: ID | null):
      Promise<{ id: ID; status: string }> {
    const q = new URLSearchParams({ decision })
    if (assignmentId) q.set('assignment_id', assignmentId)
    const { data } = await apiClient.post(`${BASE}/privileged-accounts/reviews/${reviewId}/decide?${q}`)
    return data
  },

  // --- Orphaned identity detection (§12) --- //
  async orphanedAccounts(status?: string): Promise<GovernanceFinding[]> {
    const suffix = status ? `?status=${status}` : ''
    const { data } = await apiClient.get<GovernanceFinding[]>(`${BASE}/orphaned-accounts${suffix}`)
    return data
  },
  async scanOrphanedAccounts(): Promise<OrphanedScanResult> {
    const { data } = await apiClient.post<OrphanedScanResult>(`${BASE}/orphaned-accounts/scan`)
    return data
  },

  // --- Risk scoring (§13) --- //
  async riskScores(band?: string): Promise<GovernanceRiskScore[]> {
    const suffix = band ? `?band=${band}` : ''
    const { data } = await apiClient.get<GovernanceRiskScore[]>(`${BASE}/risk-scores${suffix}`)
    return data
  },
  async recalculateRiskScores(): Promise<GovernanceRiskScore[]> {
    const { data } = await apiClient.post<GovernanceRiskScore[]>(`${BASE}/risk-scores/recalculate`)
    return data
  },

  // --- Remediation (§14) --- //
  async remediationActions(filters: { status?: string; finding_id?: ID } = {}): Promise<RemediationAction[]> {
    const q = new URLSearchParams()
    if (filters.status) q.set('status', filters.status)
    if (filters.finding_id) q.set('finding_id', filters.finding_id)
    const suffix = q.toString() ? `?${q}` : ''
    const { data } = await apiClient.get<RemediationAction[]>(`${BASE}/remediation-actions${suffix}`)
    return data
  },
  async createRemediationAction(payload: {
    finding_id: ID
    action_type: RemediationActionType
    mode?: RemediationMode
    payload?: Record<string, unknown>
  }): Promise<RemediationAction> {
    const { data } = await apiClient.post<RemediationAction>(`${BASE}/remediation-actions`, payload)
    return data
  },
  async executeRemediationAction(id: ID): Promise<RemediationAction> {
    const { data } = await apiClient.post<RemediationAction>(`${BASE}/remediation-actions/${id}/execute`)
    return data
  },

  // --- Compliance reporting (§15, §16) --- //
  async complianceFrameworks(): Promise<ComplianceFrameworkInfo[]> {
    const { data } = await apiClient.get<ComplianceFrameworkInfo[]>(`${BASE}/compliance/frameworks`)
    return data
  },
  async complianceReports(framework?: string): Promise<ComplianceReport[]> {
    const suffix = framework ? `?framework=${framework}` : ''
    const { data } = await apiClient.get<ComplianceReport[]>(`${BASE}/compliance/reports${suffix}`)
    return data
  },
  async generateComplianceReport(payload: {
    framework: string
    report_type?: string
    scope?: Record<string, unknown>
  }): Promise<ComplianceReport> {
    const { data } = await apiClient.post<ComplianceReport>(`${BASE}/compliance/reports`, payload)
    return data
  },
  async exportComplianceReportCsv(id: ID): Promise<string> {
    const { data } = await apiClient.get<string>(`${BASE}/compliance/reports/${id}`, {
      params: { format: 'csv' },
    })
    return data
  },

  ruleTypeLabel(t: RuleType): string {
    return t === 'SOD' ? 'Separation of Duties' : 'Toxic Permission'
  },
}
