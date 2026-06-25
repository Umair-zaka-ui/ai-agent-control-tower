import { useQuery } from '@tanstack/react-query'

import { QUERY_KEYS } from '@/constants/queryKeys'
import { agentService } from '@/services'
import type { ID } from '@/types'

/** List all agents in the caller's organization. */
export function useAgents() {
  return useQuery({
    queryKey: QUERY_KEYS.agents.all,
    queryFn: agentService.list,
  })
}

/** Fetch a single agent by id. */
export function useAgent(id: ID | undefined) {
  return useQuery({
    queryKey: QUERY_KEYS.agents.detail(id ?? ''),
    queryFn: () => agentService.get(id as ID),
    enabled: Boolean(id),
  })
}
