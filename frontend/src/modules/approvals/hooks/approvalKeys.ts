import type { ID } from '@/types'
import type { ApprovalListParams } from '../types'

/** TanStack Query keys for the approvals module. */
export const approvalKeys = {
  all: ['approvals'] as const,
  list: (params: ApprovalListParams) => ['approvals', 'list', params] as const,
  statistics: ['approvals', 'statistics'] as const,
  history: (params: { status?: string; search?: string }) =>
    ['approvals', 'history', params] as const,
  escalations: ['approvals', 'escalations'] as const,
  detail: (id: ID) => ['approvals', 'detail', id] as const,
  timeline: (id: ID) => ['approvals', 'timeline', id] as const,
  comments: (id: ID) => ['approvals', 'comments', id] as const,
}
