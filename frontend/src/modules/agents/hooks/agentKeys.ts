import type { ID } from '@/types'
import type { AgentListParams } from '../types'

/** TanStack Query keys for the agents module. */
export const agentKeys = {
  all: ['agents'] as const,
  list: (params: AgentListParams) => ['agents', 'list', params] as const,
  detail: (id: ID) => ['agents', 'detail', id] as const,
  stats: (id: ID) => ['agents', 'stats', id] as const,
}
