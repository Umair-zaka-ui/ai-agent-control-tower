import axios, { AxiosError, type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'

import { env } from '@/config/env'
import type { ApiError } from '@/types'
import { clearAuthStorage, getAccessToken } from '@/utils/tokenStorage'
import { refreshAccessToken } from './tokenRefresh'

/**
 * Single configured Axios instance for the whole app. Every API service is
 * built on top of this — pages and components must never import axios directly.
 *
 * - Base URL comes from `VITE_API_BASE_URL` (never hardcoded).
 * - The JWT is attached automatically when present.
 * - On a 401 (except for the auth endpoints themselves) the client attempts a
 *   one-shot refresh-token exchange and transparently retries the original
 *   request (SRS §19). If the refresh fails, it clears auth and broadcasts
 *   `act:session-expired` so the app can surface the session-expired modal.
 */
export const apiClient: AxiosInstance = axios.create({
  baseURL: env.apiBaseUrl,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30_000,
})

/** Event broadcast when the session can no longer be refreshed (SRS §20). */
export const SESSION_EXPIRED_EVENT = 'act:session-expired'

interface RetriableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean
}

apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAccessToken()
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  return config
})

/** Auth endpoints must not trigger the refresh-and-retry loop. */
function isAuthEndpoint(url: string | undefined): boolean {
  if (!url) return false
  return (
    url.includes('/auth/login') ||
    url.includes('/auth/refresh') ||
    url.includes('/auth/logout') ||
    url.includes('/auth/mfa')
  )
}

/**
 * Normalise every backend error shape into one `ApiError`.
 *
 * The identity surface answers with `{ success, error: { code, message }, request_id }`.
 * The `code` is the machine-readable half and must survive: pages branch on it to tell
 * an expired invitation from a cancelled one, or an already-verified email from an
 * invalid token (SRS 4.2.2.3.1 §18). Legacy routes answer with a plain `{ detail }` and
 * carry no code; a network failure carries neither.
 *
 * Exported for testing against the *real* wire format rather than a mock of it.
 */
export function toApiError(error: AxiosError): ApiError {
  const status = error.response?.status ?? 0
  const data = error.response?.data as
    | { detail?: unknown; message?: unknown; error?: { code?: unknown; message?: unknown } }
    | undefined
  const message =
    (typeof data?.detail === 'string' && data.detail) ||
    (typeof data?.message === 'string' && data.message) ||
    (typeof data?.error?.message === 'string' && data.error.message) ||
    error.message ||
    'Unexpected error'
  // Only trust a string. A non-string `code` is a malformed body, not a contract.
  const code = typeof data?.error?.code === 'string' ? data.error.code : undefined
  return { status, message, code, detail: data?.detail }
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const status = error.response?.status ?? 0
    const config = error.config as RetriableConfig | undefined

    // Reactive refresh: on a first 401 from a protected endpoint, try to mint a
    // new access token and replay the request exactly once.
    if (status === 401 && config && !config._retried && !isAuthEndpoint(config.url)) {
      config._retried = true
      const newToken = await refreshAccessToken()
      if (newToken) {
        config.headers.set('Authorization', `Bearer ${newToken}`)
        return apiClient(config)
      }
      // Refresh failed — the session is over.
      clearAuthStorage()
      window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT))
    }

    return Promise.reject(toApiError(error))
  },
)
