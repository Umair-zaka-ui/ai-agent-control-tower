import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { FullPageSpinner } from '@/components/common/Spinner'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'

/**
 * Gate for authenticated routes. While auth is bootstrapping from a stored
 * token we show a loading screen; unauthenticated users are sent to /login with
 * the attempted path preserved for post-login redirect.
 */
export function ProtectedRoute() {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return <FullPageSpinner />
  }

  if (!isAuthenticated) {
    return <Navigate to={ROUTES.LOGIN} replace state={{ from: location.pathname }} />
  }

  return <Outlet />
}
