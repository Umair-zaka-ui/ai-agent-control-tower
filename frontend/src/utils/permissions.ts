import type { Role } from '@/constants/roles'

/**
 * UI-level permission helpers. These gate what a user *sees*; the backend RBAC
 * layer remains the authority for what a user can actually *do*.
 */

/** True when the user's role is included in the allowed set (empty = allow all). */
export function canAccess(role: Role | undefined, allowedRoles: Role[]): boolean {
  if (allowedRoles.length === 0) return true
  if (!role) return false
  return allowedRoles.includes(role)
}

/** True when the user holds the given RBAC permission code. */
export function hasPermission(permissions: string[], code: string): boolean {
  return permissions.includes(code)
}
