import { keepPreviousData, useQuery } from '@tanstack/react-query'

import type { ID } from '@/types'
import { agentService } from '../services/agentService'
import type { AgentListParams } from '../types'
import { agentKeys } from './agentKeys'

/** Paginated, filterable agent list. Keeps previous page while fetching next. */
export function useAgents(params: AgentListParams) {
  return useQuery({
    queryKey: agentKeys.list(params),
    queryFn: () => agentService.list(params),
    placeholderData: keepPreviousData,
  })
}

/** A single agent by id. */
export function useAgent(id: ID | undefined) {
  return useQuery({
    queryKey: agentKeys.detail(id ?? ''),
    queryFn: () => agentService.get(id as ID),
    enabled: Boolean(id),
  })
}

/** Per-agent operational statistics. */
export function useAgentStats(id: ID | undefined) {
  return useQuery({
    queryKey: agentKeys.stats(id ?? ''),
    queryFn: () => agentService.stats(id as ID),
    enabled: Boolean(id),
  })
}
