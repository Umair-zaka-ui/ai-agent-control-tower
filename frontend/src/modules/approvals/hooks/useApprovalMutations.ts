import { useMutation, useQueryClient } from '@tanstack/react-query'

import type { ID } from '@/types'
import { approvalService } from '../services/approvalService'
import type { AssignInput, EscalateInput, ReviewInput } from '../types'
import { approvalKeys } from './approvalKeys'

/** Invalidate every approvals query after a mutation settles. */
function useInvalidateApprovals() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: approvalKeys.all })
}

export function useApprove() {
  const invalidate = useInvalidateApprovals()
  return useMutation({
    mutationFn: ({ id, input }: { id: ID; input?: ReviewInput }) =>
      approvalService.approve(id, input),
    onSuccess: invalidate,
  })
}

export function useReject() {
  const invalidate = useInvalidateApprovals()
  return useMutation({
    mutationFn: ({ id, input }: { id: ID; input: ReviewInput }) =>
      approvalService.reject(id, input),
    onSuccess: invalidate,
  })
}

export function useEscalate() {
  const invalidate = useInvalidateApprovals()
  return useMutation({
    mutationFn: ({ id, input }: { id: ID; input: EscalateInput }) =>
      approvalService.escalate(id, input),
    onSuccess: invalidate,
  })
}

export function useAssignReviewer() {
  const invalidate = useInvalidateApprovals()
  return useMutation({
    mutationFn: ({ id, input }: { id: ID; input: AssignInput }) =>
      approvalService.assign(id, input),
    onSuccess: invalidate,
  })
}

export function useAddComment() {
  const invalidate = useInvalidateApprovals()
  return useMutation({
    mutationFn: ({ id, comment }: { id: ID; comment: string }) =>
      approvalService.addComment(id, comment),
    onSuccess: invalidate,
  })
}
