import { useCallback } from 'react'

import { apiClient } from '@/services/apiClient'
import type { AuthorizationDecision } from './types'

/**
 * Ask the Authorization Gateway whether the current identity may perform an
 * action (§27). The server is the source of truth — `useCan` is a fast local
 * pre-check for rendering; this hook returns the *live* decision including
 * ABAC challenges and obligations, for flows that must react to them (§33).
 */
export function useAuthorize() {
  return useCallback(
    async (
      permission: string,
      options: {
        resourceType?: string
        resourceId?: string
        context?: Record<string, unknown>
      } = {},
    ): Promise<AuthorizationDecision> => {
      const { data } = await apiClient.post<AuthorizationDecision>(
        '/api/v1/authorization/check',
        {
          permission,
          resource_type: options.resourceType,
          resource_id: options.resourceId,
          context: options.context,
        },
      )
      return data
    },
    [],
  )
}
