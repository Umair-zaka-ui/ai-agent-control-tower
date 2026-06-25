import { useQuery } from '@tanstack/react-query'

import { DASHBOARD_REFRESH_MS } from '@/constants/app'
import { QUERY_KEYS } from '@/constants/queryKeys'
import { dashboardService } from '@/services'

/** Average organizational risk per day for the last N days (default 30). */
export function useRiskTrend(days = 30) {
  return useQuery({
    queryKey: QUERY_KEYS.dashboard.riskTrend(days),
    queryFn: () => dashboardService.getRiskTrend(days),
    refetchInterval: DASHBOARD_REFRESH_MS,
  })
}
