import type { Agent, AgentStatus, ApiKey, GeneratedApiKey, ID } from '@/types'
import { httpClient } from './httpClient'

/** Agents + API keys API (Phase 1 /agents, Phase 2 /agents/{id}/api-keys). */
export const agentService = {
  async list(): Promise<Agent[]> {
    const { data } = await httpClient.get<Agent[]>('/agents')
    return data
  },

  async get(id: ID): Promise<Agent> {
    const { data } = await httpClient.get<Agent>(`/agents/${id}`)
    return data
  },

  async updateStatus(id: ID, status: AgentStatus): Promise<Agent> {
    const { data } = await httpClient.patch<Agent>(`/agents/${id}/status`, { status })
    return data
  },

  async listApiKeys(id: ID): Promise<ApiKey[]> {
    const { data } = await httpClient.get<ApiKey[]>(`/agents/${id}/api-keys`)
    return data
  },

  async generateApiKey(id: ID): Promise<GeneratedApiKey> {
    const { data } = await httpClient.post<GeneratedApiKey>(`/agents/${id}/generate-api-key`, {})
    return data
  },

  async revokeApiKey(keyId: ID): Promise<void> {
    await httpClient.post(`/api-keys/${keyId}/revoke`, {})
  },
}
