import { keepPreviousData, useQuery } from '@tanstack/react-query'

import type { ID } from '@/types'
import { approvalService } from '../services/approvalService'
import type { ApprovalListParams } from '../types'
import { approvalKeys } from './approvalKeys'

/** Filterable approval queue. */
export function useApprovals(params: ApprovalListParams = {}) {
  return useQuery({
    queryKey: approvalKeys.list(params),
    queryFn: () => approvalService.list(params),
    placeholderData: keepPreviousData,
  })
}

/** A single approval's full detail payload. */
export function useApproval(id: ID | undefined) {
  return useQuery({
    queryKey: approvalKeys.detail(id ?? ''),
    queryFn: () => approvalService.get(id as ID),
    enabled: Boolean(id),
  })
}

/** Queue statistics for the dashboard cards. */
export function useApprovalStatistics() {
  return useQuery({
    queryKey: approvalKeys.statistics,
    queryFn: approvalService.statistics,
    staleTime: 30_000,
  })
}

/** Resolved approvals (history view). */
export function useApprovalHistory(params: { status?: string; search?: string } = {}) {
  return useQuery({
    queryKey: approvalKeys.history(params),
    queryFn: () => approvalService.history(params),
    placeholderData: keepPreviousData,
  })
}

/** Currently escalated approvals. */
export function useApprovalEscalations() {
  return useQuery({
    queryKey: approvalKeys.escalations,
    queryFn: approvalService.escalations,
  })
}

/** Audit-derived review timeline for an approval. */
export function useApprovalTimeline(id: ID | undefined) {
  return useQuery({
    queryKey: approvalKeys.timeline(id ?? ''),
    queryFn: () => approvalService.timeline(id as ID),
    enabled: Boolean(id),
  })
}
