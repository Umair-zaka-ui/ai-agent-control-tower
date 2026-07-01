import type { ID } from '@/types'
import type { AuditListParams } from '../types'

/** TanStack Query keys for the audit module. */
export const auditKeys = {
  all: ['audit'] as const,
  list: (params: AuditListParams) => ['audit', 'list', params] as const,
  statistics: ['audit', 'statistics'] as const,
  timeline: (limit: number) => ['audit', 'timeline', limit] as const,
  eventTypes: ['audit', 'event-types'] as const,
  security: ['audit', 'security'] as const,
  compliance: ['audit', 'compliance'] as const,
  detail: (id: ID) => ['audit', 'detail', id] as const,
}
