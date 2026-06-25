import { useContext } from 'react'

import { AuthContext, type AuthContextValue } from '@/contexts/AuthContext'

/** Access the authenticated user, permissions and login/logout actions. */
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used within an <AuthProvider>')
  }
  return ctx
}
