import { Route, Routes } from 'react-router-dom'

import { AuthLayout } from '@/layouts/AuthLayout'
import { DashboardLayout } from '@/layouts/DashboardLayout'
import { ROUTES } from '@/constants/routes'
import {
  AgentsPage,
  AnalyticsPage,
  ApprovalsPage,
  AuditPage,
  DashboardPage,
  LoginPage,
  NotFoundPage,
  PoliciesPage,
  ProfilePage,
  SettingsPage,
  UsersPage,
} from '@/pages'
import { ProtectedRoute } from './ProtectedRoute'
import { PublicRoute } from './PublicRoute'

/** Application route tree (SRS §8 navigation). */
export function AppRoutes() {
  return (
    <Routes>
      {/* Public (auth) */}
      <Route element={<PublicRoute />}>
        <Route element={<AuthLayout />}>
          <Route path={ROUTES.LOGIN} element={<LoginPage />} />
        </Route>
      </Route>

      {/* Authenticated app shell */}
      <Route element={<ProtectedRoute />}>
        <Route element={<DashboardLayout />}>
          <Route path={ROUTES.DASHBOARD} element={<DashboardPage />} />
          <Route path={ROUTES.AGENTS} element={<AgentsPage />} />
          <Route path={ROUTES.POLICIES} element={<PoliciesPage />} />
          <Route path={ROUTES.APPROVALS} element={<ApprovalsPage />} />
          <Route path={ROUTES.AUDIT} element={<AuditPage />} />
          <Route path={ROUTES.ANALYTICS} element={<AnalyticsPage />} />
          <Route path={ROUTES.USERS} element={<UsersPage />} />
          <Route path={ROUTES.SETTINGS} element={<SettingsPage />} />
          <Route path={ROUTES.PROFILE} element={<ProfilePage />} />
        </Route>
      </Route>

      {/* Fallback */}
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
