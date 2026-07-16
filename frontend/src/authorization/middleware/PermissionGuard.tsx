import type { ReactNode } from 'react'

import { RequirePermission } from '../ProtectedComponent'

/**
 * §32 — the middleware-facing name for the route/section guard. Local
 * (wildcard-aware) permission checks decide rendering; the server re-authorizes
 * every call regardless, so this is UX, not security.
 */
export function PermissionGuard({
  permission,
  children,
  redirectTo,
}: {
  permission: string
  children: ReactNode
  redirectTo?: string
}) {
  return (
    <RequirePermission permission={permission} redirectTo={redirectTo}>
      {children}
    </RequirePermission>
  )
}
