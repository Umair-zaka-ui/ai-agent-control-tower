import { apiClient } from '@/services/apiClient'
import type { AgentAction } from '@/types'
import type {
  ActivityPoint,
  ActivityRange,
  AnalyticsOverview,
  AnalyticsReport,
  CostAnalytics,
  FleetHealth,
  HumanReviewAnalytics,
  Insight,
  KpiMetric,
  PerformanceAnalytics,
  PolicyAnalytics,
  ReportPeriod,
  RiskAnalytics,
} from '../types'

/** Analytics & AI Operations Center API (Phase 3 Part 3.6). */
export const analyticsService = {
  async overview(): Promise<AnalyticsOverview> {
    const { data } = await apiClient.get<AnalyticsOverview>('/analytics/overview')
    return data
  },

  async kpis(): Promise<KpiMetric[]> {
    const { data } = await apiClient.get<KpiMetric[]>('/analytics/kpis')
    return data
  },

  async activity(range: ActivityRange = 'daily'): Promise<ActivityPoint[]> {
    const { data } = await apiClient.get<ActivityPoint[]>('/analytics/activity', {
      params: { range },
    })
    return data
  },

  async fleetHealth(): Promise<FleetHealth> {
    const { data } = await apiClient.get<FleetHealth>('/analytics/fleet-health')
    return data
  },

  async risk(): Promise<RiskAnalytics> {
    const { data } = await apiClient.get<RiskAnalytics>('/analytics/risk')
    return data
  },

  async performance(): Promise<PerformanceAnalytics> {
    const { data } = await apiClient.get<PerformanceAnalytics>('/analytics/performance')
    return data
  },

  async policies(): Promise<PolicyAnalytics> {
    const { data } = await apiClient.get<PolicyAnalytics>('/analytics/policies')
    return data
  },

  async review(): Promise<HumanReviewAnalytics> {
    const { data } = await apiClient.get<HumanReviewAnalytics>('/analytics/review')
    return data
  },

  async cost(): Promise<CostAnalytics> {
    const { data } = await apiClient.get<CostAnalytics>('/analytics/cost')
    return data
  },

  async insights(): Promise<Insight[]> {
    const { data } = await apiClient.get<Insight[]>('/analytics/insights')
    return data
  },

  async report(period: ReportPeriod = 'weekly'): Promise<AnalyticsReport> {
    const { data } = await apiClient.get<AnalyticsReport>('/analytics/reports', {
      params: { period },
    })
    return data
  },

  /** Live agent activity feed — reuses the dashboard recent-actions endpoint. */
  async recentActivity(limit = 15): Promise<AgentAction[]> {
    const { data } = await apiClient.get<AgentAction[]>('/dashboard/recent-actions', {
      params: { limit },
    })
    return data
  },
}
