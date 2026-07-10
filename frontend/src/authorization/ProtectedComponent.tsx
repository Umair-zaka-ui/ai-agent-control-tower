import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'

import { ROUTES } from '@/constants/routes'
import { useCan } from './hooks'

/**
 * Renders `children` only when the current identity holds `permission` (Phase 4.3.2
 * §23). Optionally renders `fallback` instead.
 *
 * <ProtectedComponent permission="agent.create"><CreateAgentButton /></ProtectedComponent>
 */
export function ProtectedComponent({
  permission,
  children,
  fallback = null,
}: {
  permission: string
  children: ReactNode
  fallback?: ReactNode
}) {
  return useCan(permission) ? <>{children}</> : <>{fallback}</>
}

/**
 * Route guard: renders `children` when the permission is held, otherwise redirects
 * (default: the dashboard). Compose *inside* the authenticated shell — it assumes an
 * authenticated identity whose permissions are loaded.
 */
export function RequirePermission({
  permission,
  children,
  redirectTo = ROUTES.DASHBOARD,
}: {
  permission: string
  children: ReactNode
  redirectTo?: string
}) {
  return useCan(permission) ? <>{children}</> : <Navigate to={redirectTo} replace />
}
