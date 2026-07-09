import axios from 'axios'

import { env } from '@/config/env'
import type { AuthTokenResponse } from '@/types'
import { clearAuthStorage, getRefreshToken, setAuthTokens } from '@/utils/tokenStorage'
import { unwrapEnvelope } from './envelope'

/**
 * Shared refresh-token exchange (SRS §8, §19, §20).
 *
 * Uses a *bare* axios instance (no interceptors) so refreshing never recurses
 * through the 401 handler in `apiClient`. A single in-flight promise coalesces
 * concurrent callers (the silent-refresh timer and any number of 401s) into one
 * network round-trip.
 */
const bare = axios.create({
  baseURL: env.apiBaseUrl,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30_000,
})

let inFlight: Promise<string | null> | null = null

export function refreshAccessToken(): Promise<string | null> {
  if (inFlight) return inFlight

  inFlight = (async () => {
    const refresh_token = getRefreshToken()
    if (!refresh_token) return null
    try {
      const { data: raw } = await bare.post<AuthTokenResponse>('/api/v1/auth/refresh', {
        refresh_token,
      })
      // The bare client has no interceptors, so unwrap the §5 envelope here too.
      const data = unwrapEnvelope(raw)
      setAuthTokens(data.access_token, data.refresh_token, data.expires_in)
      return data.access_token
    } catch {
      // Refresh token invalid/expired/reused — the session is over.
      clearAuthStorage()
      return null
    } finally {
      inFlight = null
    }
  })()

  return inFlight
}
