import { Navigate, Route, Routes } from 'react-router-dom'

import { ProtectedRoute } from '@/components/layout/ProtectedRoute'
import { PublicRoute } from '@/components/layout/PublicRoute'
import { AuthLayout } from '@/layouts/AuthLayout'
import { DashboardLayout } from '@/layouts/DashboardLayout'
import { ROUTES } from '@/constants/routes'
import {
  AnalyticsPage,
  ApprovalsPage,
  AuditPage,
  DashboardPage,
  LoginPage,
  NotFoundPage,
  ProfilePage,
  SettingsPage,
  UsersPage,
} from '@/pages'
import {
  AgentDetailsPage,
  AgentEditPage,
  AgentsListPage,
  CreateAgentPage,
} from '@/modules/agents'
import {
  CreatePolicyPage,
  EditPolicyPage,
  PoliciesPage,
  PolicyDetailsPage,
  PolicyTemplatesPage,
  TestPolicyPage,
} from '@/modules/policies'

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
          {/* `/` redirects to the dashboard */}
          <Route index element={<Navigate to={ROUTES.DASHBOARD} replace />} />
          <Route path={ROUTES.DASHBOARD} element={<DashboardPage />} />
          <Route path={ROUTES.AGENTS} element={<AgentsListPage />} />
          <Route path={`${ROUTES.AGENTS}/new`} element={<CreateAgentPage />} />
          <Route path={`${ROUTES.AGENTS}/:id`} element={<AgentDetailsPage />} />
          <Route path={`${ROUTES.AGENTS}/:id/edit`} element={<AgentEditPage />} />
          <Route path={ROUTES.POLICIES} element={<PoliciesPage />} />
          <Route path={`${ROUTES.POLICIES}/new`} element={<CreatePolicyPage />} />
          <Route path={`${ROUTES.POLICIES}/templates`} element={<PolicyTemplatesPage />} />
          <Route path={`${ROUTES.POLICIES}/:id`} element={<PolicyDetailsPage />} />
          <Route path={`${ROUTES.POLICIES}/:id/edit`} element={<EditPolicyPage />} />
          <Route path={`${ROUTES.POLICIES}/:id/test`} element={<TestPolicyPage />} />
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
