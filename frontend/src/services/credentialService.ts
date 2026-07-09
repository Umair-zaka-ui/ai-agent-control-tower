import type {
  AdminResetResult,
  ChangePasswordPayload,
  ID,
  PasswordDashboard,
  PasswordExpiration,
  PasswordPolicy,
  PasswordStrengthResult,
} from '@/types'
import { apiClient } from './apiClient'

/**
 * Credential management API (Part 4.2.2.3.2 §22).
 *
 * The server is the only authority on the password policy; `validate` is advisory
 * (it mirrors the meter) and `changePassword` is the gate. None of these ever
 * returns or accepts a password hash — an administrator can reset a password but
 * never see one.
 */
export const credentialService = {
  /** Change your own password. May revoke your other sessions (SRS §15). */
  async changePassword(payload: ChangePasswordPayload): Promise<{ message: string }> {
    const { data } = await apiClient.post<{ message: string }>(
      '/api/v1/auth/change-password',
      payload,
    )
    return data
  },

  /** Server-side strength/validity for the live meter (SRS §8). Rate limited. */
  async validate(password: string): Promise<PasswordStrengthResult> {
    const { data } = await apiClient.post<PasswordStrengthResult>(
      '/api/v1/auth/validate-password',
      { password },
    )
    return data
  },

  /** The active password policy, as data (SRS §5). */
  async getPolicy(): Promise<PasswordPolicy> {
    const { data } = await apiClient.get<PasswordPolicy>('/api/v1/auth/password-policy')
    return data
  },

  /** The caller's own expiry status (SRS §11). */
  async getExpiration(): Promise<PasswordExpiration> {
    const { data } = await apiClient.get<PasswordExpiration>('/api/v1/auth/password-expiration')
    return data
  },
}

/**
 * Administrative credential controls (SRS §16, §17). Require `credential.reset` /
 * `credential.dashboard`; the backend re-checks on every call and refuses to act
 * across organizations.
 */
export const adminCredentialService = {
  /** Reset a user's password, issuing a one-time temporary password (SRS §16). */
  async resetPassword(userId: ID): Promise<AdminResetResult> {
    const { data } = await apiClient.post<AdminResetResult>('/api/v1/auth/admin/reset-password', {
      user_id: userId,
    })
    return data
  },

  /** Org-wide credential posture: expired / expiring / temporary users (SRS §17). */
  async dashboard(): Promise<PasswordDashboard> {
    const { data } = await apiClient.get<PasswordDashboard>('/api/v1/security/password-dashboard')
    return data
  },
}
