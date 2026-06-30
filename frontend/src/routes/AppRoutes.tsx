import { Navigate, Route, Routes } from 'react-router-dom'

import { ProtectedRoute } from '@/components/layout/ProtectedRoute'
import { PublicRoute } from '@/components/layout/PublicRoute'
import { AuthLayout } from '@/layouts/AuthLayout'
import { DashboardLayout } from '@/layouts/DashboardLayout'
import { ROUTES } from '@/constants/routes'
import {
  AnalyticsPage,
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
import {
  ApprovalDetailsPage,
  ApprovalHistoryPage,
  ApprovalsPage,
  EscalationsPage,
  ReviewWorkbenchPage,
} from '@/modules/approvals'
import {
  AuditCompliancePage,
  AuditDashboardPage,
  AuditEventDetailPage,
  AuditEventsPage,
  AuditExportPage,
  AuditSecurityPage,
} from '@/modules/audit'

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
          <Route path={`${ROUTES.APPROVALS}/history`} element={<ApprovalHistoryPage />} />
          <Route path={`${ROUTES.APPROVALS}/escalations`} element={<EscalationsPage />} />
          <Route path={`${ROUTES.APPROVALS}/:id`} element={<ApprovalDetailsPage />} />
          <Route path={`${ROUTES.APPROVALS}/:id/review`} element={<ReviewWorkbenchPage />} />
          <Route path={ROUTES.AUDIT} element={<AuditDashboardPage />} />
          <Route path={`${ROUTES.AUDIT}/events`} element={<AuditEventsPage />} />
          <Route path={`${ROUTES.AUDIT}/security`} element={<AuditSecurityPage />} />
          <Route path={`${ROUTES.AUDIT}/compliance`} element={<AuditCompliancePage />} />
          <Route path={`${ROUTES.AUDIT}/export`} element={<AuditExportPage />} />
          <Route path={`${ROUTES.AUDIT}/:id`} element={<AuditEventDetailPage />} />
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
