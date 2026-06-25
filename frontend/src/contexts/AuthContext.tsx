import { createContext, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { authService } from '@/services'
import type { User } from '@/types'
import { getAccessToken, removeAccessToken, setAccessToken } from '@/utils/tokenStorage'

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

  /** Load the current identity + permissions using the stored token. */
  const refreshUser = useCallback(async () => {
    const me = await authService.getMe()
    setUser(me)
    try {
      const { permissions: codes } = await authService.getMyPermissions()
      setPermissions(codes)
    } catch {
      // RBAC endpoint optional for some roles — non-fatal.
      setPermissions([])
    }
  }, [])

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
      } catch {
        // Token invalid/expired — discard it.
        removeAccessToken()
        if (!cancelled) {
          setUser(null)
          setToken(null)
        }
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }
    void bootstrap()
    return () => {
      cancelled = true
    }
  }, [refreshUser])

  const login = useCallback(
    async (email: string, password: string) => {
      const { access_token } = await authService.login({ email, password })
      setAccessToken(access_token)
      setToken(access_token)
      await refreshUser()
    },
    [refreshUser],
  )

  const logout = useCallback(() => {
    authService.logout()
    setUser(null)
    setPermissions([])
    setToken(null)
  }, [])

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

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
