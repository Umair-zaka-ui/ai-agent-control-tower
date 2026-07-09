import type {
  AccountLock,
  BlockedIp,
  ID,
  LoginAttempt,
  ProtectionRule,
  ProtectionRuleWrite,
  ProtectionSummary,
  RiskEvent,
} from '@/types'
import { apiClient } from './apiClient'

/**
 * Account-protection admin API (Part 4.2.2.3.4 §20). Every call requires the
 * `security.protection` permission and is org-scoped server-side.
 */
export const protectionService = {
  async summary(): Promise<ProtectionSummary> {
    const { data } = await apiClient.get<ProtectionSummary>('/api/v1/security/account-protection/summary')
    return data
  },

  async loginAttempts(success?: boolean): Promise<LoginAttempt[]> {
    const q = success === undefined ? '' : `?success=${success}`
    const { data } = await apiClient.get<LoginAttempt[]>(`/api/v1/security/login-attempts${q}`)
    return data
  },

  async riskEvents(riskLevel?: string): Promise<RiskEvent[]> {
    const q = riskLevel ? `?risk_level=${encodeURIComponent(riskLevel)}` : ''
    const { data } = await apiClient.get<RiskEvent[]>(`/api/v1/security/risk-events${q}`)
    return data
  },

  // --- Account locks (§24, §29) --- //
  async accountLocks(status?: string): Promise<AccountLock[]> {
    const q = status ? `?status_filter=${encodeURIComponent(status)}` : ''
    const { data } = await apiClient.get<AccountLock[]>(`/api/v1/security/account-locks${q}`)
    return data
  },

  async unlockLock(lockId: ID, reason: string): Promise<AccountLock> {
    const { data } = await apiClient.post<AccountLock>(
      `/api/v1/security/account-locks/${lockId}/unlock`,
      { reason },
    )
    return data
  },

  async lockUser(userId: ID, reason = 'ADMIN_LOCKED', comment?: string): Promise<AccountLock> {
    const { data } = await apiClient.post<AccountLock>(`/api/v1/security/users/${userId}/lock`, {
      reason,
      comment,
    })
    return data
  },

  async unlockUser(userId: ID, reason: string): Promise<AccountLock[]> {
    const { data } = await apiClient.post<AccountLock[]>(`/api/v1/security/users/${userId}/unlock`, {
      reason,
    })
    return data
  },

  // --- Blocked IPs (§16) --- //
  async blockedIps(): Promise<BlockedIp[]> {
    const { data } = await apiClient.get<BlockedIp[]>('/api/v1/security/blocked-ips')
    return data
  },

  async blockIp(payload: {
    ip_address: string
    reason?: string
    expires_in_minutes?: number
  }): Promise<BlockedIp> {
    const { data } = await apiClient.post<BlockedIp>('/api/v1/security/blocked-ips', payload)
    return data
  },

  async unblockIp(id: ID): Promise<void> {
    await apiClient.delete(`/api/v1/security/blocked-ips/${id}`)
  },

  // --- Protection rules (§27) --- //
  async rules(): Promise<ProtectionRule[]> {
    const { data } = await apiClient.get<ProtectionRule[]>('/api/v1/security/identity-protection-rules')
    return data
  },

  async createRule(payload: ProtectionRuleWrite): Promise<ProtectionRule> {
    const { data } = await apiClient.post<ProtectionRule>(
      '/api/v1/security/identity-protection-rules',
      payload,
    )
    return data
  },

  async updateRule(id: ID, payload: Partial<ProtectionRuleWrite>): Promise<ProtectionRule> {
    const { data } = await apiClient.put<ProtectionRule>(
      `/api/v1/security/identity-protection-rules/${id}`,
      payload,
    )
    return data
  },

  async deleteRule(id: ID): Promise<void> {
    await apiClient.delete(`/api/v1/security/identity-protection-rules/${id}`)
  },
}
