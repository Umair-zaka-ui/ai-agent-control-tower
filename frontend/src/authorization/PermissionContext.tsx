import { createContext, useMemo, type ReactNode } from 'react'

import { useAuth } from '@/hooks/useAuth'
import { permissionGranted } from './permissions'

export interface PermissionContextValue {
  /** Effective permission codes for the current identity (from GET /auth/me). */
  permissions: string[]
  /** Wildcard-aware check: does the user hold `code`? */
  can: (code: string) => boolean
}

export const PermissionContext = createContext<PermissionContextValue | null>(null)

/**
 * Provides wildcard-aware permission checks to the tree (Phase 4.3.2 §23). Sources
 * the permission set from the auth context, so there is one source of truth on the
 * client and it refreshes whenever the identity does.
 */
export function PermissionProvider({ children }: { children: ReactNode }) {
  const { permissions } = useAuth()
  const value = useMemo<PermissionContextValue>(
    () => ({
      permissions,
      can: (code: string) => permissionGranted(permissions, code),
    }),
    [permissions],
  )
  return <PermissionContext.Provider value={value}>{children}</PermissionContext.Provider>
}
