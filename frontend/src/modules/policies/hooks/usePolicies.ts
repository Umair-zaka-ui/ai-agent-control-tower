import { keepPreviousData, useQuery } from '@tanstack/react-query'

import type { ID } from '@/types'
import { policyService } from '../services/policyService'
import type { PolicyListParams } from '../types'
import { policyKeys } from './policyKeys'

/** Filterable policy list. */
export function usePolicies(params: PolicyListParams = {}) {
  return useQuery({
    queryKey: policyKeys.list(params),
    queryFn: () => policyService.list(params),
    placeholderData: keepPreviousData,
  })
}

/** A single policy by id. */
export function usePolicy(id: ID | undefined) {
  return useQuery({
    queryKey: policyKeys.detail(id ?? ''),
    queryFn: () => policyService.get(id as ID),
    enabled: Boolean(id),
  })
}

/** Audit-trail entries for a policy. */
export function usePolicyAudit(id: ID | undefined) {
  return useQuery({
    queryKey: policyKeys.audit(id ?? ''),
    queryFn: () => policyService.audit(id as ID),
    enabled: Boolean(id),
  })
}

/** Built-in policy templates. */
export function usePolicyTemplates() {
  return useQuery({
    queryKey: policyKeys.templates,
    queryFn: policyService.templates,
    staleTime: 5 * 60_000,
  })
}
