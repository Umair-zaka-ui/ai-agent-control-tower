import type { ID } from '@/types'
import type { PolicyListParams } from '../types'

/** TanStack Query keys for the policies module. */
export const policyKeys = {
  all: ['policies'] as const,
  list: (params: PolicyListParams) => ['policies', 'list', params] as const,
  detail: (id: ID) => ['policies', 'detail', id] as const,
  audit: (id: ID) => ['policies', 'audit', id] as const,
  templates: ['policies', 'templates'] as const,
}
