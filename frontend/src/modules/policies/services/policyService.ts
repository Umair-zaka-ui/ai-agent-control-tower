import { apiClient } from '@/services/apiClient'
import type { AuditLog, ID } from '@/types'
import type {
  Policy,
  PolicyCreateInput,
  PolicyListParams,
  PolicyTemplate,
  PolicyTestRequest,
  PolicyTestResult,
  PolicyUpdateInput,
} from '../types'

/** Policy management API (Phase 3 Part 3.3). All policy HTTP lives here. */
export const policyService = {
  async list(params: PolicyListParams = {}): Promise<Policy[]> {
    const { data } = await apiClient.get<Policy[]>('/policies', { params })
    return data
  },

  async get(id: ID): Promise<Policy> {
    const { data } = await apiClient.get<Policy>(`/policies/${id}`)
    return data
  },

  async create(input: PolicyCreateInput): Promise<Policy> {
    const { data } = await apiClient.post<Policy>('/policies', input)
    return data
  },

  async update(id: ID, input: PolicyUpdateInput): Promise<Policy> {
    const { data } = await apiClient.put<Policy>(`/policies/${id}`, input)
    return data
  },

  async remove(id: ID): Promise<void> {
    await apiClient.delete(`/policies/${id}`)
  },

  async enable(id: ID): Promise<Policy> {
    const { data } = await apiClient.patch<Policy>(`/policies/${id}/enable`)
    return data
  },

  async disable(id: ID): Promise<Policy> {
    const { data } = await apiClient.patch<Policy>(`/policies/${id}/disable`)
    return data
  },

  async test(id: ID, payload: PolicyTestRequest): Promise<PolicyTestResult> {
    const { data } = await apiClient.post<PolicyTestResult>(`/policies/${id}/test`, payload)
    return data
  },

  async audit(id: ID): Promise<AuditLog[]> {
    const { data } = await apiClient.get<AuditLog[]>(`/policies/${id}/audit`)
    return data
  },

  async templates(): Promise<PolicyTemplate[]> {
    const { data } = await apiClient.get<PolicyTemplate[]>('/policies/templates')
    return data
  },
}
