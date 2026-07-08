import { AUTH_TOKEN_KEY, REFRESH_TOKEN_KEY, TOKEN_EXPIRY_KEY } from '@/constants/app'

/**
 * Auth token persistence (localStorage). Kept dependency-free so both the API
 * client and AuthContext can use it without import cycles.
 *
 * Part 4.2.2.1 adds the refresh token and the access-token expiry so the client
 * can silently refresh before expiration (SRS §20) and reactively refresh on a
 * 401 (SRS §19).
 */

// --- access token --------------------------------------------------------- //
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

// --- refresh token -------------------------------------------------------- //
export function getRefreshToken(): string | null {
  try {
    return localStorage.getItem(REFRESH_TOKEN_KEY)
  } catch {
    return null
  }
}

export function setRefreshToken(token: string): void {
  try {
    localStorage.setItem(REFRESH_TOKEN_KEY, token)
  } catch {
    /* storage unavailable — ignore */
  }
}

// --- access-token expiry (epoch ms) --------------------------------------- //
export function getTokenExpiry(): number | null {
  try {
    const raw = localStorage.getItem(TOKEN_EXPIRY_KEY)
    return raw ? Number(raw) : null
  } catch {
    return null
  }
}

export function setTokenExpiry(epochMs: number): void {
  try {
    localStorage.setItem(TOKEN_EXPIRY_KEY, String(epochMs))
  } catch {
    /* storage unavailable — ignore */
  }
}

/**
 * Persist a freshly issued token pair together with its computed expiry.
 * ``expiresInSeconds`` is the access-token lifetime returned by the API.
 */
export function setAuthTokens(
  accessToken: string,
  refreshToken: string | null,
  expiresInSeconds: number,
): void {
  setAccessToken(accessToken)
  if (refreshToken) setRefreshToken(refreshToken)
  setTokenExpiry(Date.now() + expiresInSeconds * 1000)
}

/** Remove every persisted auth artifact (access + refresh + expiry). */
export function clearAuthStorage(): void {
  try {
    localStorage.removeItem(AUTH_TOKEN_KEY)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
    localStorage.removeItem(TOKEN_EXPIRY_KEY)
  } catch {
    /* storage unavailable — ignore */
  }
}
