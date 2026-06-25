import { Navigate, Outlet } from 'react-router-dom'

import { FullPageSpinner } from '@/components/common/Spinner'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'

/**
 * Gate for unauthenticated-only routes (login). Authenticated users are sent
 * straight to the dashboard.
 */
export function PublicRoute() {
  const { isAuthenticated, isLoading } = useAuth()

  if (isLoading) {
    return <FullPageSpinner />
  }

  if (isAuthenticated) {
    return <Navigate to={ROUTES.DASHBOARD} replace />
  }

  return <Outlet />
}
