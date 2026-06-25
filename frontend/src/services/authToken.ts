import { AUTH_TOKEN_KEY } from '@/constants/app'

/**
 * Tiny token store. Kept separate from the http client and AuthContext so both
 * can read/write the persisted JWT without importing each other (avoids cycles).
 */
export const tokenStore = {
  get(): string | null {
    try {
      return localStorage.getItem(AUTH_TOKEN_KEY)
    } catch {
      return null
    }
  },
  set(token: string): void {
    try {
      localStorage.setItem(AUTH_TOKEN_KEY, token)
    } catch {
      /* storage unavailable — ignore */
    }
  },
  clear(): void {
    try {
      localStorage.removeItem(AUTH_TOKEN_KEY)
    } catch {
      /* storage unavailable — ignore */
    }
  },
}
