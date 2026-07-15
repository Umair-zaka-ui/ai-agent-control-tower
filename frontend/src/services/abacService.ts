import type {
  ABACAttribute,
  ABACDecision,
  ABACEvaluationRow,
  ABACPolicy,
  ABACPolicyException,
  ABACPolicyVersion,
  ABACPolicyWrite,
  ABACSimulation,
  ABACValidationResult,
  ID,
} from '@/types'
import { apiClient } from './apiClient'

const BASE = '/api/v1/authorization'

/**
 * ABAC engine API (Phase 4.3.5, mounted at /api/v1/authorization).
 * Gated by the §37 permission set (authorization.abac.*); authoring and
 * publishing are separable roles server-side.
 */
export const abacService = {
  // --- Policies (§30) --- //
  async policies(status?: string): Promise<ABACPolicy[]> {
    const { data } = await apiClient.get<ABACPolicy[]>(`${BASE}/abac/policies`, {
      params: status ? { status } : undefined,
    })
    return data
  },
  async policy(id: ID): Promise<ABACPolicy> {
    const { data } = await apiClient.get<ABACPolicy>(`${BASE}/abac/policies/${id}`)
    return data
  },
  async createPolicy(payload: ABACPolicyWrite): Promise<ABACPolicy> {
    const { data } = await apiClient.post<ABACPolicy>(`${BASE}/abac/policies`, payload)
    return data
  },
  async updatePolicy(id: ID, payload: ABACPolicyWrite): Promise<ABACPolicy> {
    const { data } = await apiClient.put<ABACPolicy>(`${BASE}/abac/policies/${id}`, payload)
    return data
  },
  async deletePolicy(id: ID): Promise<void> {
    await apiClient.delete(`${BASE}/abac/policies/${id}`)
  },

  // --- Lifecycle --- //
  async validatePolicy(id: ID): Promise<ABACValidationResult> {
    const { data } = await apiClient.post<ABACValidationResult>(
      `${BASE}/abac/policies/${id}/validate`,
    )
    return data
  },
  async publishPolicy(id: ID): Promise<ABACPolicy> {
    const { data } = await apiClient.post<ABACPolicy>(`${BASE}/abac/policies/${id}/publish`)
    return data
  },
  async disablePolicy(id: ID): Promise<ABACPolicy> {
    const { data } = await apiClient.post<ABACPolicy>(`${BASE}/abac/policies/${id}/disable`)
    return data
  },
  async archivePolicy(id: ID): Promise<ABACPolicy> {
    const { data } = await apiClient.post<ABACPolicy>(`${BASE}/abac/policies/${id}/archive`)
    return data
  },
  async clonePolicy(id: ID): Promise<ABACPolicy> {
    const { data } = await apiClient.post<ABACPolicy>(`${BASE}/abac/policies/${id}/clone`)
    return data
  },

  // --- Versions --- //
  async versions(id: ID): Promise<ABACPolicyVersion[]> {
    const { data } = await apiClient.get<ABACPolicyVersion[]>(
      `${BASE}/abac/policies/${id}/versions`,
    )
    return data
  },
  async rollback(id: ID, version: number): Promise<ABACPolicy> {
    const { data } = await apiClient.post<ABACPolicy>(
      `${BASE}/abac/policies/${id}/rollback/${version}`,
    )
    return data
  },

  // --- Simulation (§35) --- //
  async simulate(payload: {
    action: string
    identity_id?: ID | null
    resource_pk?: ID | null
    context?: Record<string, unknown>
    policy?: Record<string, unknown> | null
  }): Promise<ABACSimulation> {
    const { data } = await apiClient.post<ABACSimulation>(`${BASE}/abac/simulate`, payload)
    return data
  },
  async simulatePolicy(id: ID, payload: {
    action: string
    identity_id?: ID | null
    resource_pk?: ID | null
    context?: Record<string, unknown>
  }): Promise<ABACSimulation> {
    const { data } = await apiClient.post<ABACSimulation>(
      `${BASE}/abac/policies/${id}/simulate`, payload,
    )
    return data
  },

  // --- Evaluation (§30, §36) --- //
  async evaluate(payload: {
    action: string
    resource_pk?: ID | null
    context?: Record<string, unknown>
  }): Promise<ABACDecision> {
    const { data } = await apiClient.post<ABACDecision>(`${BASE}/abac/evaluate`, payload)
    return data
  },
  async evaluations(decision?: string): Promise<ABACEvaluationRow[]> {
    const { data } = await apiClient.get<ABACEvaluationRow[]>(`${BASE}/abac/evaluations`, {
      params: decision ? { decision } : undefined,
    })
    return data
  },
  async evaluation(id: ID): Promise<ABACEvaluationRow> {
    const { data } = await apiClient.get<ABACEvaluationRow>(`${BASE}/abac/evaluations/${id}`)
    return data
  },
  async metrics(): Promise<Record<string, number>> {
    const { data } = await apiClient.get<Record<string, number>>(`${BASE}/abac/metrics`)
    return data
  },

  // --- Attributes (§20) --- //
  async attributes(category?: string): Promise<ABACAttribute[]> {
    const { data } = await apiClient.get<ABACAttribute[]>(`${BASE}/attributes`, {
      params: category ? { category } : undefined,
    })
    return data
  },
  async createAttribute(payload: {
    name: string
    category: string
    data_type: string
    description?: string | null
    sensitivity?: string
  }): Promise<ABACAttribute> {
    const { data } = await apiClient.post<ABACAttribute>(`${BASE}/attributes`, payload)
    return data
  },
  async updateAttribute(id: ID, payload: {
    description?: string | null
    sensitivity?: string
    enabled?: boolean
  }): Promise<ABACAttribute> {
    const { data } = await apiClient.put<ABACAttribute>(`${BASE}/attributes/${id}`, payload)
    return data
  },

  // --- Exceptions (§21) --- //
  async exceptions(): Promise<ABACPolicyException[]> {
    const { data } = await apiClient.get<ABACPolicyException[]>(`${BASE}/exceptions`)
    return data
  },
  async createException(payload: {
    policy_id: ID
    subject_id: ID
    subject_type?: string
    reason?: string | null
    valid_until: string
  }): Promise<ABACPolicyException> {
    const { data } = await apiClient.post<ABACPolicyException>(`${BASE}/exceptions`, payload)
    return data
  },
  async revokeException(id: ID): Promise<ABACPolicyException> {
    const { data } = await apiClient.delete<ABACPolicyException>(`${BASE}/exceptions/${id}`)
    return data
  },
}
