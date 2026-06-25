import { useQuery } from '@tanstack/react-query'

import { DASHBOARD_REFRESH_MS } from '@/constants/app'
import { QUERY_KEYS } from '@/constants/queryKeys'
import { dashboardService } from '@/services'

/** Headline KPI counts. Auto-refreshes every 60s (SRS Part 3.1). */
export function useDashboardSummary() {
  return useQuery({
    queryKey: QUERY_KEYS.dashboard.summary,
    queryFn: dashboardService.getSummary,
    refetchInterval: DASHBOARD_REFRESH_MS,
  })
}
