import { apiClient } from '@/services/apiClient'
import type { ID } from '@/types'
import type {
  Agent,
  AgentCreateInput,
  AgentCreateResponse,
  AgentListParams,
  AgentListResponse,
  AgentStats,
  AgentStatus,
  AgentUpdateInput,
} from '../types'

/** Agent management API (Phase 3 Part 3.2). All agent HTTP lives here. */
export const agentService = {
  async list(params: AgentListParams): Promise<AgentListResponse> {
    const { data } = await apiClient.get<AgentListResponse>('/agents', { params })
    return data
  },

  async get(id: ID): Promise<Agent> {
    const { data } = await apiClient.get<Agent>(`/agents/${id}`)
    return data
  },

  async create(input: AgentCreateInput): Promise<AgentCreateResponse> {
    const { data } = await apiClient.post<AgentCreateResponse>('/agents', input)
    return data
  },

  async update(id: ID, input: AgentUpdateInput): Promise<Agent> {
    const { data } = await apiClient.put<Agent>(`/agents/${id}`, input)
    return data
  },

  async updateStatus(id: ID, status: AgentStatus): Promise<Agent> {
    const { data } = await apiClient.patch<Agent>(`/agents/${id}/status`, { status })
    return data
  },

  async remove(id: ID): Promise<void> {
    await apiClient.delete(`/agents/${id}`)
  },

  async stats(id: ID): Promise<AgentStats> {
    const { data } = await apiClient.get<AgentStats>(`/agents/${id}/stats`)
    return data
  },
}
