import { useMutation, useQueryClient } from '@tanstack/react-query'

import type { ID } from '@/types'
import { agentService } from '../services/agentService'
import type { AgentCreateInput, AgentStatus, AgentUpdateInput } from '../types'
import { agentKeys } from './agentKeys'

/** Invalidate all agent queries after a mutation. */
function useInvalidateAgents() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: agentKeys.all })
}

export function useCreateAgent() {
  const invalidate = useInvalidateAgents()
  return useMutation({
    mutationFn: (input: AgentCreateInput) => agentService.create(input),
    onSuccess: invalidate,
  })
}

export function useUpdateAgent() {
  const invalidate = useInvalidateAgents()
  return useMutation({
    mutationFn: ({ id, input }: { id: ID; input: AgentUpdateInput }) =>
      agentService.update(id, input),
    onSuccess: invalidate,
  })
}

export function useUpdateAgentStatus() {
  const invalidate = useInvalidateAgents()
  return useMutation({
    mutationFn: ({ id, status }: { id: ID; status: AgentStatus }) =>
      agentService.updateStatus(id, status),
    onSuccess: invalidate,
  })
}

export function useDeleteAgent() {
  const invalidate = useInvalidateAgents()
  return useMutation({
    mutationFn: (id: ID) => agentService.remove(id),
    onSuccess: invalidate,
  })
}
