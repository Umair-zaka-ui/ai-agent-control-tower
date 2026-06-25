import { useQuery } from '@tanstack/react-query'

import { DASHBOARD_REFRESH_MS } from '@/constants/app'
import { QUERY_KEYS } from '@/constants/queryKeys'
import { systemService } from '@/services'

/** Subsystem health for the System Health widget. */
export function useSystemHealth() {
  return useQuery({
    queryKey: QUERY_KEYS.system.health,
    queryFn: systemService.getHealth,
    refetchInterval: DASHBOARD_REFRESH_MS,
  })
}
