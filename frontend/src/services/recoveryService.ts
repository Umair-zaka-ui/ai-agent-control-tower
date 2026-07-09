import type {
  ChangeEmailPayload,
  RecoveryAck,
  RecoveryEvent,
  ResetPasswordPayload,
} from '@/types'
import { apiClient } from './apiClient'

/**
 * Account recovery API (Part 4.2.2.3.3 §21).
 *
 * The public endpoints (`forgotPassword`, `resetPassword`, `verifyNewEmail`) are
 * unauthenticated and rate limited server-side. `forgotPassword` answers identically
 * whether or not the account exists (§9) — the UI must never imply the address was
 * recognised.
 */
export const recoveryService = {
  /** Request a reset link. Always resolves the same way; never an existence oracle. */
  async forgotPassword(email: string): Promise<RecoveryAck> {
    const { data } = await apiClient.post<RecoveryAck>('/api/v1/auth/forgot-password', { email })
    return data
  },

  /** Redeem a reset token and set a new password. Revokes every session server-side. */
  async resetPassword(payload: ResetPasswordPayload): Promise<RecoveryAck> {
    const { data } = await apiClient.post<RecoveryAck>('/api/v1/auth/reset-password', payload)
    return data
  },

  /** Request an email change (authenticated). Confirmation goes to the new address. */
  async changeEmail(payload: ChangeEmailPayload): Promise<RecoveryAck> {
    const { data } = await apiClient.post<RecoveryAck>('/api/v1/auth/change-email', payload)
    return data
  },

  /** Confirm a new email address from its token, swapping it in. */
  async verifyNewEmail(token: string): Promise<RecoveryAck> {
    const { data } = await apiClient.post<RecoveryAck>('/api/v1/auth/verify-new-email', { token })
    return data
  },
}

/** Administrative recovery view (§18). Requires `recovery.view`. */
export const adminRecoveryService = {
  async events(limit = 100): Promise<RecoveryEvent[]> {
    const { data } = await apiClient.get<RecoveryEvent[]>(
      `/api/v1/security/recovery-events?limit=${limit}`,
    )
    return data
  },
}
