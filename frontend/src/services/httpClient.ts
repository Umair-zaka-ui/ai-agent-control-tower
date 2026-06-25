import axios, { AxiosError, type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'

import { env } from '@/config/env'
import type { ApiError } from '@/types'
import { tokenStore } from './authToken'

/**
 * Single configured Axios instance for the whole app. Every API service is
 * built on top of this — pages and components must never import axios directly.
 */
export const httpClient: AxiosInstance = axios.create({
  baseURL: env.apiBaseUrl,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30_000,
})

// Attach the bearer token on every request when present.
httpClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = tokenStore.get()
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }
  return config
})

// Normalise errors into a predictable ApiError and handle auth expiry.
httpClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const status = error.response?.status ?? 0

    // Token expired/invalid — drop it so the app routes back to login.
    if (status === 401) {
      tokenStore.clear()
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
