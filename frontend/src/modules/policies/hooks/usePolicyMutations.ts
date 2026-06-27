import { useMutation, useQueryClient } from '@tanstack/react-query'

import type { ID } from '@/types'
import { policyService } from '../services/policyService'
import type { PolicyCreateInput, PolicyTestRequest, PolicyUpdateInput } from '../types'
import { policyKeys } from './policyKeys'

function useInvalidatePolicies() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: policyKeys.all })
}

export function useCreatePolicy() {
  const invalidate = useInvalidatePolicies()
  return useMutation({
    mutationFn: (input: PolicyCreateInput) => policyService.create(input),
    onSuccess: invalidate,
  })
}

export function useUpdatePolicy() {
  const invalidate = useInvalidatePolicies()
  return useMutation({
    mutationFn: ({ id, input }: { id: ID; input: PolicyUpdateInput }) =>
      policyService.update(id, input),
    onSuccess: invalidate,
  })
}

export function useDeletePolicy() {
  const invalidate = useInvalidatePolicies()
  return useMutation({
    mutationFn: (id: ID) => policyService.remove(id),
    onSuccess: invalidate,
  })
}

/** Enable or disable a policy. */
export function useTogglePolicy() {
  const invalidate = useInvalidatePolicies()
  return useMutation({
    mutationFn: ({ id, enable }: { id: ID; enable: boolean }) =>
      enable ? policyService.enable(id) : policyService.disable(id),
    onSuccess: invalidate,
  })
}

/** Simulate an action against a policy (no cache mutation). */
export function useTestPolicy() {
  return useMutation({
    mutationFn: ({ id, payload }: { id: ID; payload: PolicyTestRequest }) =>
      policyService.test(id, payload),
  })
}
