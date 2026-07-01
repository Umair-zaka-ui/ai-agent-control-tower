/**
 * Identity UI permissions. The backend RBAC layer is the authority; these only
 * decide which controls are shown. Permission codes are namespaced (SRS §12).
 */
export function canViewIdentity(permissions: string[]): boolean {
  return permissions.includes('user.view')
}

export function canManageIdentity(permissions: string[]): boolean {
  return permissions.includes('user.create')
}
