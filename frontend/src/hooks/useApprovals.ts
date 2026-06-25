import { useQuery } from '@tanstack/react-query'

import { QUERY_KEYS } from '@/constants/queryKeys'
import { approvalService } from '@/services'

/** List pending approvals awaiting human review. */
export function usePendingApprovals() {
  return useQuery({
    queryKey: QUERY_KEYS.approvals.pending,
    queryFn: approvalService.listPending,
  })
}
