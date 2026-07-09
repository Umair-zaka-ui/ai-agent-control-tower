import { Navigate, Outlet } from 'react-router-dom'

import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'

/**
 * Blocks the authenticated app while a password change is outstanding (4.2.2.3.2
 * §11, §13). An expired or temporary/admin-reset password grants a session but no
 * access to features: the user is sent to the forced-change page and cannot reach
 * anything else until the server confirms the change.
 *
 * Sits *inside* ProtectedRoute (so it only runs for signed-in users) and *around*
 * the dashboard shell — never around the forced-change page itself, which would
 * loop.
 */
export function PasswordChangeGuard() {
  const { passwordChangeRequired } = useAuth()

  if (passwordChangeRequired) {
    return <Navigate to={ROUTES.FORCE_PASSWORD_CHANGE} replace />
  }

  return <Outlet />
}
