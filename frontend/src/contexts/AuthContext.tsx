import { createContext, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { authService, tokenStore } from '@/services'
import type { User } from '@/types'

export interface AuthContextValue {
  user: User | null
  permissions: string[]
  isAuthenticated: boolean
  /** True while bootstrapping auth from a persisted token on first load. */
  isInitializing: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

// eslint-disable-next-line react-refresh/only-export-components
export const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [permissions, setPermissions] = useState<string[]>([])
  const [isInitializing, setIsInitializing] = useState<boolean>(true)

  /** Load the current identity + permissions using the stored token. */
  const loadIdentity = useCallback(async () => {
    const me = await authService.me()
    setUser(me)
    try {
      const { permissions: codes } = await authService.myPermissions()
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
      if (!tokenStore.get()) {
        setIsInitializing(false)
        return
      }
      try {
        await loadIdentity()
      } catch {
        tokenStore.clear()
        if (!cancelled) setUser(null)
      } finally {
        if (!cancelled) setIsInitializing(false)
      }
    }
    void bootstrap()
    return () => {
      cancelled = true
    }
  }, [loadIdentity])

  const login = useCallback(
    async (email: string, password: string) => {
      const { access_token } = await authService.login({ email, password })
      tokenStore.set(access_token)
      await loadIdentity()
    },
    [loadIdentity],
  )

  const logout = useCallback(() => {
    tokenStore.clear()
    setUser(null)
    setPermissions([])
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      permissions,
      isAuthenticated: user !== null,
      isInitializing,
      login,
      logout,
    }),
    [user, permissions, isInitializing, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
