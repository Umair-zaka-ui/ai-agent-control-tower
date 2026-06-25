import type { AuthTokenResponse, EffectivePermissions, LoginRequest, User } from '@/types'
import { removeAccessToken } from '@/utils/tokenStorage'
import { apiClient } from './apiClient'

/** Auth + identity API (Phase 1 /auth, Phase 2 /rbac/me). */
export const authService = {
  async login(payload: LoginRequest): Promise<AuthTokenResponse> {
    const { data } = await apiClient.post<AuthTokenResponse>('/auth/login', payload)
    return data
  },

  /** Current authenticated user (GET /auth/me). */
  async getMe(): Promise<User> {
    const { data } = await apiClient.get<User>('/auth/me')
    return data
  },

  /** Effective RBAC permission codes (GET /rbac/me). */
  async getMyPermissions(): Promise<EffectivePermissions> {
    const { data } = await apiClient.get<EffectivePermissions>('/rbac/me')
    return data
  },

  /**
   * Client-side logout. The backend uses stateless JWTs, so logging out means
   * discarding the token locally. Kept here so all auth I/O lives in one place.
   */
  logout(): void {
    removeAccessToken()
  },
}
