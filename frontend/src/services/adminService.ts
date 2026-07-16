import type {
  AccessReviewCampaign,
  AccessReviewItem,
  AdminDashboard,
  AuthorizationDecisionRow,
  ID,
  SecurityAnalytics,
} from '@/types'
import { apiClient } from './apiClient'

const BASE = '/api/v1/admin'

/**
 * Administration portal API (Phase 4.3.7 §18, mounted at /api/v1/admin).
 * Every call is re-authorized server-side against the admin.* permission set
 * (§21); all mutations are audited.
 */
export const adminService = {
  async dashboard(): Promise<AdminDashboard> {
    const { data } = await apiClient.get<AdminDashboard>(`${BASE}/dashboard`)
    return data
  },
  async analytics(): Promise<SecurityAnalytics> {
    const { data } = await apiClient.get<SecurityAnalytics>(`${BASE}/analytics`)
    return data
  },

  // --- Decision explorer (§13) --- //
  async decisions(filters: {
    identityId?: ID
    permission?: string
    resourceType?: string
    allowed?: boolean
    since?: string
    until?: string
    limit?: number
  } = {}): Promise<AuthorizationDecisionRow[]> {
    const q = new URLSearchParams()
    if (filters.identityId) q.set('identity_id', filters.identityId)
    if (filters.permission) q.set('permission', filters.permission)
    if (filters.resourceType) q.set('resource_type', filters.resourceType)
    if (filters.allowed !== undefined) q.set('allowed', String(filters.allowed))
    if (filters.since) q.set('since', filters.since)
    if (filters.until) q.set('until', filters.until)
    q.set('limit', String(filters.limit ?? 100))
    const { data } = await apiClient.get<AuthorizationDecisionRow[]>(
      `${BASE}/authorization-decisions?${q}`,
    )
    return data
  },

  // --- Access reviews (§14) --- //
  async campaigns(status?: string): Promise<AccessReviewCampaign[]> {
    const suffix = status ? `?status=${status}` : ''
    const { data } = await apiClient.get<AccessReviewCampaign[]>(
      `${BASE}/access-reviews${suffix}`,
    )
    return data
  },
  async createCampaign(payload: {
    name: string
    description?: string
    scope?: Record<string, unknown>
    due_at?: string
  }): Promise<AccessReviewCampaign> {
    const { data } = await apiClient.post<AccessReviewCampaign>(
      `${BASE}/access-reviews`, payload,
    )
    return data
  },
  async activateCampaign(id: ID): Promise<AccessReviewCampaign> {
    const { data } = await apiClient.post<AccessReviewCampaign>(
      `${BASE}/access-reviews/${id}/activate`,
    )
    return data
  },
  async completeCampaign(id: ID): Promise<AccessReviewCampaign> {
    const { data } = await apiClient.post<AccessReviewCampaign>(
      `${BASE}/access-reviews/${id}/complete`,
    )
    return data
  },
  async archiveCampaign(id: ID): Promise<AccessReviewCampaign> {
    const { data } = await apiClient.post<AccessReviewCampaign>(
      `${BASE}/access-reviews/${id}/archive`,
    )
    return data
  },
  async campaignItems(id: ID): Promise<AccessReviewItem[]> {
    const { data } = await apiClient.get<AccessReviewItem[]>(
      `${BASE}/access-reviews/${id}/items`,
    )
    return data
  },
  async decideItem(campaignId: ID, itemId: ID, decision: 'CERTIFIED' | 'REVOKED',
                   comment?: string): Promise<AccessReviewItem> {
    const { data } = await apiClient.post<AccessReviewItem>(
      `${BASE}/access-reviews/${campaignId}/items/${itemId}/decide`,
      { decision, comment },
    )
    return data
  },
  async exportCampaign(id: ID): Promise<Record<string, unknown>> {
    const { data } = await apiClient.get<Record<string, unknown>>(
      `${BASE}/access-reviews/${id}/export`,
    )
    return data
  },
}
