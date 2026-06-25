import { useQuery } from '@tanstack/react-query'

import { DASHBOARD_REFRESH_MS } from '@/constants/app'
import { QUERY_KEYS } from '@/constants/queryKeys'
import { dashboardService } from '@/services'

/** Most recent agent actions across the organization. */
export function useRecentActions(limit = 8) {
  return useQuery({
    queryKey: QUERY_KEYS.dashboard.recentActions,
    queryFn: () => dashboardService.getRecentActions(limit),
    refetchInterval: DASHBOARD_REFRESH_MS,
  })
}
