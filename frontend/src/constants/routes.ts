/**
 * Canonical route paths. Import these instead of hardcoding URL strings so
 * navigation stays refactor-safe across the app.
 */
export const ROUTES = {
  // Auth
  LOGIN: '/login',

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
  PROFILE: '/profile',

  // Misc
  NOT_FOUND: '/404',
} as const

export type RoutePath = (typeof ROUTES)[keyof typeof ROUTES]
