import { Navigate, Route, Routes } from 'react-router-dom'

import { ProtectedRoute } from '@/components/layout/ProtectedRoute'
import { PasswordChangeGuard } from '@/components/layout/PasswordChangeGuard'
import { PublicRoute } from '@/components/layout/PublicRoute'
import { AuthLayout } from '@/layouts/AuthLayout'
import { DashboardLayout } from '@/layouts/DashboardLayout'
import { ROUTES } from '@/constants/routes'
import {
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
import { SecuritySessionsPage } from '@/modules/security'
import {
  AccountLocksPage,
  BlockedIpsPage,
  IdentityProtectionRulesPage,
  LoginAttemptsPage,
  RiskEventsPage,
  SecurityDashboardPage,
} from '@/modules/protection'
import {
  AuthorizationAuditPage,
  PermissionGroupsPage,
  PermissionsPage,
  RoleAssignmentsPage,
  RoleHierarchyPage,
  RolesPage,
} from '@/modules/authorization'
import {
  BusinessUnitsPage,
  DelegatedAdministrationPage,
  DepartmentsPage,
  HierarchyExplorerPage,
  OrganizationsPage,
  ProjectsPage,
  TeamsPage,
} from '@/modules/hierarchy'
import {
  AuthorizationInspectorPage,
  DelegationManagementPage,
  OwnershipTransferPage,
  ResourceACLPage,
  ResourcePermissionsPage,
  ResourceSharingPage,
} from '@/modules/resources'
import {
  AccessReviewsPage,
  AdminDashboardPage,
  DecisionExplorerPage,
  SecurityAnalyticsPage,
} from '@/modules/admin'
import {
  ABACEvaluationsPage,
  ABACPoliciesPage,
  ABACPolicyDetailsPage,
  ABACPolicyVersionsPage,
  AttributeCatalogPage,
  CreateABACPolicyPage,
  EditABACPolicyPage,
  PolicyExceptionsPage,
  PolicySimulatorPage,
} from '@/modules/abac'
import {
  AcceptInvitationPage,
  ChangeEmailPage,
  ChangePasswordPage,
  ForcedPasswordChangePage,
  ForgotPasswordPage,
  InvitationExpiredPage,
  RecoverySuccessPage,
  RegisterPage,
  RegistrationSuccessPage,
  ResetPasswordPage,
  SecurityPasswordDashboard,
  SecurityRecoveryDashboard,
  VerifyEmailPage,
  VerifyNewEmailPage,
} from '@/modules/identity/pages'
import {
  AgentsAnalyticsPage,
  AnalyticsOverviewPage,
  CostDashboardPage,
  ExecutiveDashboardPage,
  OperationsDashboardPage,
  PerformanceDashboardPage,
  PolicyAnalyticsPage,
  ReportsCenterPage,
  RiskAnalyticsPage,
} from '@/modules/analytics'
import { IdentityPage } from '@/modules/identity'

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

      {/*
        Onboarding (Part 4.2.2.3.1 §16). Deliberately *outside* PublicRoute: that guard
        redirects authenticated users to the dashboard, which would silently swallow a
        verification link clicked by someone already signed in on that browser.
      */}
      <Route element={<AuthLayout />}>
        <Route path={ROUTES.REGISTER} element={<RegisterPage />} />
        <Route path={ROUTES.ACCEPT_INVITATION} element={<AcceptInvitationPage />} />
        <Route path={ROUTES.VERIFY_EMAIL} element={<VerifyEmailPage />} />
        <Route path={ROUTES.INVITATION_EXPIRED} element={<InvitationExpiredPage />} />
        <Route path={ROUTES.REGISTRATION_SUCCESS} element={<RegistrationSuccessPage />} />
        {/* Recovery (Part 4.2.2.3.3 §22). Public: the user cannot sign in. */}
        <Route path={ROUTES.FORGOT_PASSWORD} element={<ForgotPasswordPage />} />
        <Route path={ROUTES.RESET_PASSWORD} element={<ResetPasswordPage />} />
        <Route path={ROUTES.RECOVERY_SUCCESS} element={<RecoverySuccessPage />} />
        <Route path={ROUTES.VERIFY_NEW_EMAIL} element={<VerifyNewEmailPage />} />
      </Route>

      {/* Authenticated app shell */}
      <Route element={<ProtectedRoute />}>
        {/*
          Forced password change (4.2.2.3.2 §11, §13). Inside ProtectedRoute but
          OUTSIDE the change guard, so it is reachable while a change is pending.
        */}
        <Route element={<AuthLayout />}>
          <Route path={ROUTES.FORCE_PASSWORD_CHANGE} element={<ForcedPasswordChangePage />} />
        </Route>

        <Route element={<PasswordChangeGuard />}>
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
          <Route path={ROUTES.IDENTITY} element={<IdentityPage />} />
          <Route path={ROUTES.ANALYTICS} element={<AnalyticsOverviewPage />} />
          <Route path={`${ROUTES.ANALYTICS}/executive`} element={<ExecutiveDashboardPage />} />
          <Route path={`${ROUTES.ANALYTICS}/operations`} element={<OperationsDashboardPage />} />
          <Route path={`${ROUTES.ANALYTICS}/risk`} element={<RiskAnalyticsPage />} />
          <Route path={`${ROUTES.ANALYTICS}/performance`} element={<PerformanceDashboardPage />} />
          <Route path={`${ROUTES.ANALYTICS}/agents`} element={<AgentsAnalyticsPage />} />
          <Route path={`${ROUTES.ANALYTICS}/policies`} element={<PolicyAnalyticsPage />} />
          <Route path={`${ROUTES.ANALYTICS}/costs`} element={<CostDashboardPage />} />
          <Route path={`${ROUTES.ANALYTICS}/reports`} element={<ReportsCenterPage />} />
          <Route path={ROUTES.USERS} element={<UsersPage />} />
          <Route path={ROUTES.SETTINGS} element={<SettingsPage />} />
          <Route path={ROUTES.SETTINGS_SECURITY} element={<SecuritySessionsPage />} />
          <Route path={ROUTES.CHANGE_PASSWORD} element={<ChangePasswordPage />} />
          <Route path={ROUTES.SECURITY_PASSWORDS} element={<SecurityPasswordDashboard />} />
          <Route path={ROUTES.CHANGE_EMAIL} element={<ChangeEmailPage />} />
          <Route path={ROUTES.SECURITY_RECOVERY} element={<SecurityRecoveryDashboard />} />
          {/* Account protection console (4.2.2.3.4 §22) */}
          <Route path={ROUTES.SECURITY_PROTECTION} element={<SecurityDashboardPage />} />
          <Route path={ROUTES.SECURITY_LOGIN_ATTEMPTS} element={<LoginAttemptsPage />} />
          <Route path={ROUTES.SECURITY_RISK_EVENTS} element={<RiskEventsPage />} />
          <Route path={ROUTES.SECURITY_ACCOUNT_LOCKS} element={<AccountLocksPage />} />
          <Route path={ROUTES.SECURITY_PROTECTION_RULES} element={<IdentityProtectionRulesPage />} />
          <Route path={ROUTES.SECURITY_BLOCKED_IPS} element={<BlockedIpsPage />} />
          {/* Enterprise Authorization portal (Phase 4.3.1 §21) */}
          <Route path={ROUTES.AUTHZ_ROLES} element={<RolesPage />} />
          <Route path={ROUTES.AUTHZ_PERMISSIONS} element={<PermissionsPage />} />
          <Route path={ROUTES.AUTHZ_PERMISSION_GROUPS} element={<PermissionGroupsPage />} />
          <Route path={ROUTES.AUTHZ_ASSIGNMENTS} element={<RoleAssignmentsPage />} />
          <Route path={ROUTES.AUTHZ_HIERARCHY} element={<RoleHierarchyPage />} />
          <Route path={ROUTES.AUTHZ_AUDIT} element={<AuthorizationAuditPage />} />
          {/* Enterprise organization hierarchy (Phase 4.3.3 §16) */}
          <Route path={ROUTES.ORG_EXPLORER} element={<HierarchyExplorerPage />} />
          <Route path={ROUTES.ORG_ORGANIZATIONS} element={<OrganizationsPage />} />
          <Route path={ROUTES.ORG_BUSINESS_UNITS} element={<BusinessUnitsPage />} />
          <Route path={ROUTES.ORG_DEPARTMENTS} element={<DepartmentsPage />} />
          <Route path={ROUTES.ORG_TEAMS} element={<TeamsPage />} />
          <Route path={ROUTES.ORG_PROJECTS} element={<ProjectsPage />} />
          <Route path={ROUTES.ORG_DELEGATION} element={<DelegatedAdministrationPage />} />
          {/* Resource-based authorization portal (Phase 4.3.4 §20) */}
          <Route path={ROUTES.RES_PERMISSIONS} element={<ResourcePermissionsPage />} />
          <Route path={ROUTES.RES_ACL} element={<ResourceACLPage />} />
          <Route path={ROUTES.RES_SHARING} element={<ResourceSharingPage />} />
          <Route path={ROUTES.RES_OWNERSHIP} element={<OwnershipTransferPage />} />
          <Route path={ROUTES.RES_DELEGATION} element={<DelegationManagementPage />} />
          <Route path={ROUTES.RES_INSPECTOR} element={<AuthorizationInspectorPage />} />
          {/* Authorization administration portal (Phase 4.3.7 §5) */}
          <Route path={ROUTES.ADMIN_DASHBOARD} element={<AdminDashboardPage />} />
          <Route path={ROUTES.ADMIN_DECISIONS} element={<DecisionExplorerPage />} />
          <Route path={ROUTES.ADMIN_REVIEWS} element={<AccessReviewsPage />} />
          <Route path={ROUTES.ADMIN_ANALYTICS} element={<SecurityAnalyticsPage />} />
          {/* ABAC administration (Phase 4.3.5 §33) */}
          <Route path={ROUTES.ABAC_POLICIES} element={<ABACPoliciesPage />} />
          <Route path={`${ROUTES.ABAC_POLICIES}/new`} element={<CreateABACPolicyPage />} />
          <Route path={ROUTES.ABAC_SIMULATOR} element={<PolicySimulatorPage />} />
          <Route path={`${ROUTES.ABAC_POLICIES}/:id`} element={<ABACPolicyDetailsPage />} />
          <Route path={`${ROUTES.ABAC_POLICIES}/:id/edit`} element={<EditABACPolicyPage />} />
          <Route path={`${ROUTES.ABAC_POLICIES}/:id/versions`} element={<ABACPolicyVersionsPage />} />
          <Route path={ROUTES.ABAC_ATTRIBUTES} element={<AttributeCatalogPage />} />
          <Route path={ROUTES.ABAC_EVALUATIONS} element={<ABACEvaluationsPage />} />
          <Route path={ROUTES.ABAC_EXCEPTIONS} element={<PolicyExceptionsPage />} />
          <Route path={ROUTES.PROFILE} element={<ProfilePage />} />
        </Route>
        </Route>
      </Route>

      {/* Fallback */}
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
