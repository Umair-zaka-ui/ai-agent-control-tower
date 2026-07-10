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
  /** View pending invitations (4.2.2.3.1 §15). */
  INVITATION_VIEW: 'invitation.view',
  /** Create, resend and cancel invitations. */
  INVITATION_MANAGE: 'invitation.manage',
  /** Reset another user's password / issue temporary credentials (4.2.2.3.2 §16). */
  CREDENTIAL_RESET: 'credential.reset',
  /** View the org password/credential dashboard (4.2.2.3.2 §17). */
  CREDENTIAL_DASHBOARD: 'credential.dashboard',
  /** View password-reset & recovery events (4.2.2.3.3 §18). */
  RECOVERY_VIEW: 'recovery.view',
  /** View/manage account protection: locks, blocked IPs, rules (4.2.2.3.4 §20). */
  SECURITY_PROTECTION: 'security.protection',
  /** View roles, permissions, groups and assignments (Phase 4.3.1 §20). */
  ROLE_VIEW: 'role.view',
  /** Create/edit/archive/delete roles, permissions and hierarchy (4.3.1 §20). */
  ROLE_MANAGE: 'role.manage',
  /** Assign and remove roles, including scoped assignments (4.3.1 §20). */
  ROLE_ASSIGN: 'role.assign',
  /** View the organization hierarchy, ownership and delegations (4.3.3 §15). */
  ORGANIZATION_VIEW: 'organization.view',
  /** Manage business units, departments, teams, projects, ownership, delegation. */
  ORGANIZATION_MANAGE: 'organization.manage',
} as const

export type Permission = (typeof PERMISSIONS)[keyof typeof PERMISSIONS]
