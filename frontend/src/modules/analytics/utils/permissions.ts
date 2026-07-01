/**
 * Analytics UI permissions (SRS §Security). The backend RBAC layer is the
 * authority; these decide which analytics surfaces are shown.
 *
 * - analytics.view       → general analytics (overview, risk, performance,
 *                          agents, policies, costs, reports)
 * - analytics.executive  → executive dashboard
 * - analytics.operations → operations dashboard
 */
export function canViewAnalytics(permissions: string[]): boolean {
  return permissions.includes('analytics.view')
}

export function canViewExecutive(permissions: string[]): boolean {
  return permissions.includes('analytics.executive')
}

export function canViewOperations(permissions: string[]): boolean {
  return permissions.includes('analytics.operations')
}
