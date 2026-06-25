/**
 * Application roles (SRS §2). These mirror the governance personas the
 * dashboard is built around. The backend's RBAC layer is the source of truth
 * for real permission checks; this enum is used for UI gating and labels.
 */
export const ROLES = {
  SUPER_ADMIN: 'SUPER_ADMIN',
  ADMIN: 'ADMIN',
  REVIEWER: 'REVIEWER',
  AUDITOR: 'AUDITOR',
  OPERATOR: 'OPERATOR',
} as const

export type Role = (typeof ROLES)[keyof typeof ROLES]

export const ROLE_LABELS: Record<Role, string> = {
  SUPER_ADMIN: 'Super Administrator',
  ADMIN: 'Organization Admin',
  REVIEWER: 'Reviewer',
  AUDITOR: 'Auditor',
  OPERATOR: 'Operator',
}
