import { AUTH_TOKEN_KEY } from '@/constants/app'

/**
 * JWT access-token persistence (Phase 3 uses localStorage). Kept dependency-free
 * so both the API client and AuthContext can use it without import cycles.
 */

export function getAccessToken(): string | null {
  try {
    return localStorage.getItem(AUTH_TOKEN_KEY)
  } catch {
    return null
  }
}

export function setAccessToken(token: string): void {
  try {
    localStorage.setItem(AUTH_TOKEN_KEY, token)
  } catch {
    /* storage unavailable — ignore */
  }
}

export function removeAccessToken(): void {
  try {
    localStorage.removeItem(AUTH_TOKEN_KEY)
  } catch {
    /* storage unavailable — ignore */
  }
}
