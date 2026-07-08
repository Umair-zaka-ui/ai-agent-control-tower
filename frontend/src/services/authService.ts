import type { AuthTokenResponse, LoginRequest, MeResponse } from '@/types'
import { clearAuthStorage } from '@/utils/tokenStorage'
import { apiClient } from './apiClient'
import { refreshAccessToken } from './tokenRefresh'

/**
 * Human authentication API (Part 4.2.2.1, mounted at /api/v1/auth).
 * All auth I/O lives here so token handling stays in one place.
 */
export const authService = {
  /** Exchange email + password for an access + refresh token pair (SRS §6). */
  async login(payload: LoginRequest): Promise<AuthTokenResponse> {
    const { data } = await apiClient.post<AuthTokenResponse>('/api/v1/auth/login', payload)
    return data
  },

  /** Current identity, roles and effective permissions (GET /api/v1/auth/me). */
  async getMe(): Promise<MeResponse> {
    const { data } = await apiClient.get<MeResponse>('/api/v1/auth/me')
    return data
  },

  /** Silent/reactive token refresh — returns the new access token or null. */
  refresh: refreshAccessToken,

  /**
   * Server-side logout: revoke the session + refresh-token family (SRS §7),
   * then clear local storage. Best-effort — local state is cleared regardless.
   */
  async logout(): Promise<void> {
    try {
      await apiClient.post('/api/v1/auth/logout')
    } catch {
      /* already unauthenticated / offline — clear locally anyway */
    }
    clearAuthStorage()
  },
}
