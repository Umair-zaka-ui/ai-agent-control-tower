import { useQuery } from '@tanstack/react-query'

import { apiClient } from '@/services/apiClient'
import type { ID } from '@/types'

/** Minimal user shape returned by GET /users (backend UserRead). */
export interface OrgUser {
  id: ID
  name: string
  email: string
  role: string
}

/** Organization members, used to populate reviewer pickers (assign / escalate). */
export function useOrgUsers() {
  return useQuery({
    queryKey: ['approvals', 'org-users'],
    queryFn: async () => {
      const { data } = await apiClient.get<OrgUser[]>('/users')
      return data
    },
    staleTime: 5 * 60_000,
  })
}
