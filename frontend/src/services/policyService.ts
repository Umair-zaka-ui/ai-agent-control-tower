import type { ID, Policy, PolicyInput } from '@/types'
import { httpClient } from './httpClient'

/** Policy engine API (Phase 2 /policies). */
export const policyService = {
  async list(params?: { resource?: string; action?: string }): Promise<Policy[]> {
    const { data } = await httpClient.get<Policy[]>('/policies', { params })
    return data
  },

  async get(id: ID): Promise<Policy> {
    const { data } = await httpClient.get<Policy>(`/policies/${id}`)
    return data
  },

  async create(payload: PolicyInput): Promise<Policy> {
    const { data } = await httpClient.post<Policy>('/policies', payload)
    return data
  },

  async update(id: ID, payload: Partial<PolicyInput>): Promise<Policy> {
    const { data } = await httpClient.patch<Policy>(`/policies/${id}`, payload)
    return data
  },

  async remove(id: ID): Promise<void> {
    await httpClient.delete(`/policies/${id}`)
  },
}
