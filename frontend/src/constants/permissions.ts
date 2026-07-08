/**
 * Backend RBAC permission codes the UI gates on.
 *
 * The backend is the source of truth — every one of these is re-checked
 * server-side. Gating here only hides controls the user could not use anyway;
 * it is never the security boundary.
 */
export const PERMISSIONS = {
  /** View any user's sessions and devices in the organization (SRS §17). */
  SESSION_VIEW: 'session.view',
  /** Force-logout another user's sessions (SRS §17). */
  SESSION_REVOKE: 'session.revoke',
  /** List organization members (needed for the admin user picker). */
  USER_VIEW: 'user.view',
} as const

export type Permission = (typeof PERMISSIONS)[keyof typeof PERMISSIONS]
