import { useQuery } from '@tanstack/react-query'

import { analyticsService } from '../services/analyticsService'
import type { ActivityRange, ReportPeriod } from '../types'
import { REFRESH, analyticsKeys } from './analyticsKeys'

/** Composite landing payload (KPIs, fleet, risk, activity, insights). */
export function useAnalyticsOverview() {
  return useQuery({
    queryKey: analyticsKeys.overview,
    queryFn: analyticsService.overview,
    refetchInterval: REFRESH.dashboard,
  })
}

/** Executive KPI tiles. */
export function useExecutiveDashboard() {
  return useQuery({
    queryKey: analyticsKeys.kpis,
    queryFn: analyticsService.kpis,
    refetchInterval: REFRESH.kpis,
  })
}

/** Activity series for the selected granularity. */
export function useActivity(range: ActivityRange = 'daily') {
  return useQuery({
    queryKey: analyticsKeys.activity(range),
    queryFn: () => analyticsService.activity(range),
    refetchInterval: REFRESH.charts,
  })
}

export function useFleetHealth() {
  return useQuery({
    queryKey: analyticsKeys.fleetHealth,
    queryFn: analyticsService.fleetHealth,
    refetchInterval: REFRESH.dashboard,
  })
}

export function useRiskAnalytics() {
  return useQuery({
    queryKey: analyticsKeys.risk,
    queryFn: analyticsService.risk,
    refetchInterval: REFRESH.charts,
  })
}

export function usePerformanceAnalytics() {
  return useQuery({
    queryKey: analyticsKeys.performance,
    queryFn: analyticsService.performance,
    refetchInterval: REFRESH.charts,
  })
}

export function usePolicyAnalytics() {
  return useQuery({
    queryKey: analyticsKeys.policies,
    queryFn: analyticsService.policies,
    refetchInterval: REFRESH.charts,
  })
}

export function useHumanReviewAnalytics() {
  return useQuery({
    queryKey: analyticsKeys.review,
    queryFn: analyticsService.review,
    refetchInterval: REFRESH.charts,
  })
}

export function useCostAnalytics() {
  return useQuery({
    queryKey: analyticsKeys.cost,
    queryFn: analyticsService.cost,
    refetchInterval: REFRESH.charts,
  })
}

export function useInsights() {
  return useQuery({
    queryKey: analyticsKeys.insights,
    queryFn: analyticsService.insights,
    refetchInterval: REFRESH.dashboard,
  })
}

export function useReports(period: ReportPeriod = 'weekly') {
  return useQuery({
    queryKey: analyticsKeys.report(period),
    queryFn: () => analyticsService.report(period),
  })
}

/** Live agent activity feed (10s refresh). */
export function useActivityFeed(limit = 15) {
  return useQuery({
    queryKey: analyticsKeys.feed,
    queryFn: () => analyticsService.recentActivity(limit),
    refetchInterval: REFRESH.feed,
  })
}
