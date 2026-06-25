import type { ID, Policy, PolicyInput } from '@/types'
import { apiClient } from './apiClient'

/** Policy engine API (Phase 2 /policies). */
export const policyService = {
  async list(params?: { resource?: string; action?: string }): Promise<Policy[]> {
    const { data } = await apiClient.get<Policy[]>('/policies', { params })
    return data
  },

  async get(id: ID): Promise<Policy> {
    const { data } = await apiClient.get<Policy>(`/policies/${id}`)
    return data
  },

  async create(payload: PolicyInput): Promise<Policy> {
    const { data } = await apiClient.post<Policy>('/policies', payload)
    return data
  },

  async update(id: ID, payload: Partial<PolicyInput>): Promise<Policy> {
    const { data } = await apiClient.patch<Policy>(`/policies/${id}`, payload)
    return data
  },

  async remove(id: ID): Promise<void> {
    await apiClient.delete(`/policies/${id}`)
  },
}
