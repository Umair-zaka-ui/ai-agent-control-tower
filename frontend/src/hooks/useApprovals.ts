import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { DASHBOARD_REFRESH_MS } from '@/constants/app'
import { QUERY_KEYS } from '@/constants/queryKeys'
import { approvalService, dashboardService } from '@/services'
import type { ID } from '@/types'

/** Pending approvals shown on the dashboard. Auto-refreshes every 60s. */
export function usePendingApprovals() {
  return useQuery({
    queryKey: QUERY_KEYS.dashboard.pendingApprovals,
    queryFn: dashboardService.getPendingApprovals,
    refetchInterval: DASHBOARD_REFRESH_MS,
  })
}

/**
 * Approve / reject mutations for the dashboard approval widget. On success they
 * invalidate the approval, summary and recent-action feeds so the UI updates.
 */
export function useApprovalActions() {
  const queryClient = useQueryClient()

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.pendingApprovals })
    void queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.summary })
    void queryClient.invalidateQueries({ queryKey: QUERY_KEYS.dashboard.recentActions })
  }

  const approve = useMutation({
    mutationFn: (id: ID) => approvalService.approve(id),
    onSuccess: invalidate,
  })

  const reject = useMutation({
    mutationFn: (id: ID) => approvalService.reject(id),
    onSuccess: invalidate,
  })

  return { approve, reject }
}
