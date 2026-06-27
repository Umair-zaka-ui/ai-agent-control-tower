import type { Role } from '@/constants/roles'

/**
 * Policy UI permissions (SRS §Role-Based UI). The backend RBAC layer remains the
 * authority; these gate what's shown.
 *
 * - ADMIN / SUPER_ADMIN: create, edit, delete, enable/disable
 * - REVIEWER: view + test
 * - VIEWER (and anything else): view only
 */
const MANAGER_ROLES = new Set<string>(['ADMIN', 'SUPER_ADMIN'])
const TESTER_ROLES = new Set<string>(['ADMIN', 'SUPER_ADMIN', 'REVIEWER'])

export function canManagePolicies(role: Role | string | undefined): boolean {
  return role != null && MANAGER_ROLES.has(role)
}

export function canTestPolicies(role: Role | string | undefined): boolean {
  return role != null && TESTER_ROLES.has(role)
}
