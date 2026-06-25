import type { AgentAction, Approval, DashboardSummary } from '@/types'
import { apiClient } from './apiClient'

/** Dashboard aggregation API (Phase 2 /dashboard/*). */
export const dashboardService = {
  async summary(): Promise<DashboardSummary> {
    const { data } = await apiClient.get<DashboardSummary>('/dashboard/summary')
    return data
  },

  async recentActions(): Promise<AgentAction[]> {
    const { data } = await apiClient.get<AgentAction[]>('/dashboard/recent-actions')
    return data
  },

  async highRiskActions(): Promise<AgentAction[]> {
    const { data } = await apiClient.get<AgentAction[]>('/dashboard/high-risk-actions')
    return data
  },

  async pendingApprovals(): Promise<Approval[]> {
    const { data } = await apiClient.get<Approval[]>('/dashboard/pending-approvals')
    return data
  },
}
