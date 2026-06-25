import type { AuthTokenResponse, EffectivePermissions, LoginRequest, User } from '@/types'
import { httpClient } from './httpClient'

/** Auth + identity API (Phase 1 /auth, Phase 2 /rbac/me). */
export const authService = {
  async login(payload: LoginRequest): Promise<AuthTokenResponse> {
    const { data } = await httpClient.post<AuthTokenResponse>('/auth/login', payload)
    return data
  },

  async me(): Promise<User> {
    const { data } = await httpClient.get<User>('/auth/me')
    return data
  },

  async myPermissions(): Promise<EffectivePermissions> {
    const { data } = await httpClient.get<EffectivePermissions>('/rbac/me')
    return data
  },
}
