import { useContext } from 'react'

import { PermissionContext, type PermissionContextValue } from './PermissionContext'

/** Access the permission set + `can()` (Phase 4.3.2 §23). */
export function usePermissions(): PermissionContextValue {
  const ctx = useContext(PermissionContext)
  if (!ctx) {
    throw new Error('usePermissions must be used within a <PermissionProvider>')
  }
  return ctx
}

/**
 * `const canCreate = useCan('agent.create')` (§24). Wildcard-aware, reactive to the
 * current identity. The server still enforces the real decision.
 */
export function useCan(code: string): boolean {
  return usePermissions().can(code)
}
