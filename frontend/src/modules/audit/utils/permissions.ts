/**
 * Audit UI permissions (SRS §Security). The backend RBAC layer is the
 * authority; these only decide which surfaces and controls are shown.
 *
 * Permission codes come from the RBAC catalog:
 * - audit.view   → dashboard, events table, event detail
 * - audit.export → export center, security & compliance dashboards, raw payloads
 */
export function canViewAudit(permissions: string[]): boolean {
  return permissions.includes('audit.view')
}

export function canExportAudit(permissions: string[]): boolean {
  return permissions.includes('audit.export')
}
