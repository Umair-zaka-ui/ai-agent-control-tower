import { createContext, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import { SessionExpiredModal } from '@/components/auth/SessionExpiredModal'
import { ROUTES } from '@/constants/routes'
import { SILENT_REFRESH_LEAD_MS } from '@/constants/app'
import { authService } from '@/services'
import { SESSION_EXPIRED_EVENT } from '@/services/apiClient'
import type { User } from '@/types'
import {
  clearAuthStorage,
  getAccessToken,
  getTokenExpiry,
  setAuthTokens,
} from '@/utils/tokenStorage'

export interface AuthContextValue {
  user: User | null
  token: string | null
  permissions: string[]
  isAuthenticated: boolean
  /** True while bootstrapping auth from a persisted token on first load. */
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  refreshUser: () => Promise<void>
}

// eslint-disable-next-line react-refresh/only-export-components
export const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [permissions, setPermissions] = useState<string[]>([])
  const [token, setToken] = useState<string | null>(() => getAccessToken())
  const [isLoading, setIsLoading] = useState<boolean>(true)
  const [sessionExpired, setSessionExpired] = useState<boolean>(false)
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  /** Load the current identity + permissions from GET /api/v1/auth/me. */
  const refreshUser = useCallback(async () => {
    const me = await authService.getMe()
    setUser(me.user)
    setPermissions(me.permissions ?? [])
  }, [])

  const clearRefreshTimer = useCallback(() => {
    if (refreshTimer.current) {
      clearTimeout(refreshTimer.current)
      refreshTimer.current = null
    }
  }, [])

  /**
   * Schedule a silent refresh 5 minutes before the persisted expiry (SRS §20).
   * Reads the expiry from storage so it works both after login and after a
   * reactive refresh performed by the API client.
   */
  const scheduleSilentRefresh = useCallback(() => {
    clearRefreshTimer()
    const expiry = getTokenExpiry()
    if (!expiry) return
    const delay = Math.max(expiry - Date.now() - SILENT_REFRESH_LEAD_MS, 0)
    refreshTimer.current = setTimeout(async () => {
      const newToken = await authService.refresh()
      if (newToken) {
        setToken(newToken)
        scheduleSilentRefresh()
      } else {
        // Cannot refresh — surface the session-expired modal.
        window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT))
      }
    }, delay)
  }, [clearRefreshTimer])

  const applySessionExpired = useCallback(() => {
    clearRefreshTimer()
    clearAuthStorage()
    setUser(null)
    setPermissions([])
    setToken(null)
    setSessionExpired(true)
  }, [clearRefreshTimer])

  // Listen for the API client's session-expired broadcast (failed 401 refresh).
  useEffect(() => {
    const handler = () => applySessionExpired()
    window.addEventListener(SESSION_EXPIRED_EVENT, handler)
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, handler)
  }, [applySessionExpired])

  // Bootstrap from a persisted token on first mount.
  useEffect(() => {
    let cancelled = false
    async function bootstrap() {
      if (!getAccessToken()) {
        setIsLoading(false)
        return
      }
      try {
        await refreshUser()
        if (!cancelled) scheduleSilentRefresh()
      } catch {
        // Access token invalid — try a one-shot refresh before giving up.
        const newToken = await authService.refresh()
        if (newToken && !cancelled) {
          try {
            await refreshUser()
            setToken(newToken)
            scheduleSilentRefresh()
          } catch {
            clearAuthStorage()
            if (!cancelled) {
              setUser(null)
              setToken(null)
            }
          }
        } else {
          clearAuthStorage()
          if (!cancelled) {
            setUser(null)
            setToken(null)
          }
        }
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }
    void bootstrap()
    return () => {
      cancelled = true
      clearRefreshTimer()
    }
  }, [refreshUser, scheduleSilentRefresh, clearRefreshTimer])

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await authService.login({ email, password })
      if (res.mfa_required) {
        // Second-factor flow is delivered in a later subpart; no MFA UI yet.
        throw new Error('Multi-factor authentication is required for this account.')
      }
      setAuthTokens(res.access_token, res.refresh_token, res.expires_in)
      setToken(res.access_token)
      setSessionExpired(false)
      await refreshUser()
      scheduleSilentRefresh()
    },
    [refreshUser, scheduleSilentRefresh],
  )

  const logout = useCallback(() => {
    clearRefreshTimer()
    void authService.logout()
    setUser(null)
    setPermissions([])
    setToken(null)
    setSessionExpired(false)
  }, [clearRefreshTimer])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      permissions,
      isAuthenticated: user !== null,
      isLoading,
      login,
      logout,
      refreshUser,
    }),
    [user, token, permissions, isLoading, login, logout, refreshUser],
  )

  return (
    <AuthContext.Provider value={value}>
      {children}
      <SessionExpiredModal
        open={sessionExpired}
        onConfirm={() => {
          setSessionExpired(false)
          window.location.assign(ROUTES.LOGIN)
        }}
      />
    </AuthContext.Provider>
  )
}
