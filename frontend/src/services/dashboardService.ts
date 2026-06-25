import type {
  AgentAction,
  Approval,
  AuditLog,
  DashboardActivity,
  DashboardSummary,
  RiskTrend,
} from '@/types'
import { apiClient } from './apiClient'

/** Dashboard aggregation API (Phase 2 + Phase 3.1 /dashboard/*). */
export const dashboardService = {
  async getSummary(): Promise<DashboardSummary> {
    const { data } = await apiClient.get<DashboardSummary>('/dashboard/summary')
    return data
  },

  async getActivity(days = 7): Promise<DashboardActivity[]> {
    const { data } = await apiClient.get<DashboardActivity[]>('/dashboard/activity', {
      params: { days },
    })
    return data
  },

  async getRiskTrend(days = 30): Promise<RiskTrend[]> {
    const { data } = await apiClient.get<RiskTrend[]>('/dashboard/risk-trend', {
      params: { days },
    })
    return data
  },

  async getRecentActions(limit = 8): Promise<AgentAction[]> {
    const { data } = await apiClient.get<AgentAction[]>('/dashboard/recent-actions', {
      params: { limit },
    })
    return data
  },

  async getPendingApprovals(): Promise<Approval[]> {
    const { data } = await apiClient.get<Approval[]>('/dashboard/pending-approvals')
    return data
  },

  async getRecentAuditLogs(limit = 6): Promise<AuditLog[]> {
    const { data } = await apiClient.get<AuditLog[]>('/audit-logs', { params: { limit } })
    return data
  },
}
