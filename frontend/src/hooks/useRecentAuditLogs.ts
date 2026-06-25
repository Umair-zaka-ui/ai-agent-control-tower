import { useQuery } from '@tanstack/react-query'

import { DASHBOARD_REFRESH_MS } from '@/constants/app'
import { QUERY_KEYS } from '@/constants/queryKeys'
import { dashboardService } from '@/services'

/** Most recent audit-log entries for the dashboard feed. */
export function useRecentAuditLogs(limit = 6) {
  return useQuery({
    queryKey: QUERY_KEYS.dashboard.recentAuditLogs,
    queryFn: () => dashboardService.getRecentAuditLogs(limit),
    refetchInterval: DASHBOARD_REFRESH_MS,
  })
}
