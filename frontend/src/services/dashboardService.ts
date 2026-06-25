import type { AgentAction, Approval, DashboardSummary } from '@/types'
import { httpClient } from './httpClient'

/** Dashboard aggregation API (Phase 2 /dashboard/*). */
export const dashboardService = {
  async summary(): Promise<DashboardSummary> {
    const { data } = await httpClient.get<DashboardSummary>('/dashboard/summary')
    return data
  },

  async recentActions(): Promise<AgentAction[]> {
    const { data } = await httpClient.get<AgentAction[]>('/dashboard/recent-actions')
    return data
  },

  async highRiskActions(): Promise<AgentAction[]> {
    const { data } = await httpClient.get<AgentAction[]>('/dashboard/high-risk-actions')
    return data
  },

  async pendingApprovals(): Promise<Approval[]> {
    const { data } = await httpClient.get<Approval[]>('/dashboard/pending-approvals')
    return data
  },
}
