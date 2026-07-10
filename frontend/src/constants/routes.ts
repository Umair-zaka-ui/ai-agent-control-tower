/**
 * Canonical route paths. Import these instead of hardcoding URL strings so
 * navigation stays refactor-safe across the app.
 */
export const ROUTES = {
  // Auth
  LOGIN: '/login',

  // Onboarding (Part 4.2.2.3.1 §16). Public: the user has no account yet.
  // The token paths must match the links the backend emails:
  // `identity/email/service.py::invitation_url` / `verification_url`.
  REGISTER: '/register',
  ACCEPT_INVITATION: '/invite/:token',
  VERIFY_EMAIL: '/verify-email/:token',
  INVITATION_EXPIRED: '/invitation-expired',
  REGISTRATION_SUCCESS: '/registration-success',

  // Recovery (Part 4.2.2.3.3 §22). Public: the user cannot sign in.
  FORGOT_PASSWORD: '/forgot-password',
  RESET_PASSWORD: '/reset-password/:token',
  RECOVERY_SUCCESS: '/recovery-success',
  VERIFY_NEW_EMAIL: '/verify-new-email/:token',

  // Dashboard (app shell). `/` redirects to `/dashboard`.
  ROOT: '/',
  DASHBOARD: '/dashboard',
  AGENTS: '/agents',
  POLICIES: '/policies',
  APPROVALS: '/approvals',
  AUDIT: '/audit',
  ANALYTICS: '/analytics',
  IDENTITY: '/identity',
  USERS: '/users',
  SETTINGS: '/settings',
  /** Settings → Security → Sessions (SRS 4.2.2.2 §24). */
  SETTINGS_SECURITY: '/settings/security',
  /** Change your own password (4.2.2.3.2 §23). */
  CHANGE_PASSWORD: '/settings/security/password',
  /** Admin password dashboard (4.2.2.3.2 §17, §23). */
  SECURITY_PASSWORDS: '/settings/security/passwords',
  /** Change your own email (4.2.2.3.3 §12). */
  CHANGE_EMAIL: '/settings/security/email',
  /** Admin recovery-events dashboard (4.2.2.3.3 §18). */
  SECURITY_RECOVERY: '/settings/security/recovery',
  /** Account protection console (4.2.2.3.4 §22). */
  SECURITY_PROTECTION: '/settings/security/protection',
  SECURITY_LOGIN_ATTEMPTS: '/settings/security/login-attempts',
  SECURITY_RISK_EVENTS: '/settings/security/risk-events',
  SECURITY_ACCOUNT_LOCKS: '/settings/security/account-locks',
  SECURITY_PROTECTION_RULES: '/settings/security/protection-rules',
  SECURITY_BLOCKED_IPS: '/settings/security/blocked-ips',
  /** Enterprise Authorization portal (Phase 4.3.1 §21). */
  AUTHZ_ROLES: '/settings/authorization/roles',
  AUTHZ_PERMISSIONS: '/settings/authorization/permissions',
  AUTHZ_PERMISSION_GROUPS: '/settings/authorization/permission-groups',
  AUTHZ_ASSIGNMENTS: '/settings/authorization/assignments',
  AUTHZ_HIERARCHY: '/settings/authorization/hierarchy',
  AUTHZ_AUDIT: '/settings/authorization/audit',
  /**
   * Forced password change (4.2.2.3.2 §11, §13). Outside the dashboard shell and
   * NOT behind the change guard, so it is the one place the user can go while a
   * change is outstanding.
   */
  FORCE_PASSWORD_CHANGE: '/account/password-change',
  PROFILE: '/profile',

  // Misc
  NOT_FOUND: '/404',
} as const

export type RoutePath = (typeof ROUTES)[keyof typeof ROUTES]
