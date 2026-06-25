import axios, { AxiosError, type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'

import { env } from '@/config/env'
import { ROUTES } from '@/constants/routes'
import type { ApiError } from '@/types'
import { getAccessToken, removeAccessToken } from '@/utils/tokenStorage'

/**
 * Single configured Axios instance for the whole app. Every API service is
 * built on top of this — pages and components must never import axios directly.
 *
 * - Base URL comes from `VITE_API_BASE_URL` (never hardcoded).
 * - The JWT is attached automatically when present; requests without a token
 *   still proceed (public endpoints work).
 * - A 401 response clears the token and redirects to /login (except when the
 *   failing call is the login request itself, which surfaces an inline error).
 */
export const apiClient: AxiosInstance = axios.create({
  baseURL: env.apiBaseUrl,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30_000,
})

apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAccessToken()
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  return config
})

function isLoginRequest(config: AxiosError['config']): boolean {
  return Boolean(config?.url && config.url.includes('/auth/login'))
}

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const status = error.response?.status ?? 0

    if (status === 401 && !isLoginRequest(error.config)) {
      removeAccessToken()
      // Hard redirect so all in-memory auth state is discarded. Guarded to
      // avoid a redirect loop when we're already on the login page.
      if (window.location.pathname !== ROUTES.LOGIN) {
        window.location.assign(ROUTES.LOGIN)
      }
    }

    const data = error.response?.data as { detail?: unknown; message?: unknown } | undefined
    const message =
      (typeof data?.detail === 'string' && data.detail) ||
      (typeof data?.message === 'string' && data.message) ||
      error.message ||
      'Unexpected error'

    const apiError: ApiError = { status, message, detail: data?.detail }
    return Promise.reject(apiError)
  },
)
