import { useQuery } from '@tanstack/react-query'

import { QUERY_KEYS } from '@/constants/queryKeys'
import { dashboardService } from '@/services'

/**
 * Dashboard data hooks. Wired to the Phase 2 /dashboard endpoints; the UI that
 * consumes them is built out in a later Part. Pages call these — never axios.
 */
export function useDashboardSummary() {
  return useQuery({
    queryKey: QUERY_KEYS.dashboard.summary,
    queryFn: dashboardService.summary,
  })
}

export function useRecentActions() {
  return useQuery({
    queryKey: QUERY_KEYS.dashboard.recentActions,
    queryFn: dashboardService.recentActions,
  })
}

export function useHighRiskActions() {
  return useQuery({
    queryKey: QUERY_KEYS.dashboard.highRiskActions,
    queryFn: dashboardService.highRiskActions,
  })
}
