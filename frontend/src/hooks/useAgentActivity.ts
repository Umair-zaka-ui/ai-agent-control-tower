import { useQuery } from '@tanstack/react-query'

import { DASHBOARD_REFRESH_MS } from '@/constants/app'
import { QUERY_KEYS } from '@/constants/queryKeys'
import { dashboardService } from '@/services'

/** Daily agent-action counts for the last N days (default 7). */
export function useAgentActivity(days = 7) {
  return useQuery({
    queryKey: QUERY_KEYS.dashboard.activity(days),
    queryFn: () => dashboardService.getActivity(days),
    refetchInterval: DASHBOARD_REFRESH_MS,
  })
}
