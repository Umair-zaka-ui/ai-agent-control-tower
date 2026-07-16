// Enterprise Permission Engine — frontend integration (Phase 4.3.2 §23, §24).
export { PermissionProvider, PermissionContext } from './PermissionContext'
export type { PermissionContextValue } from './PermissionContext'
export { usePermissions, useCan } from './hooks'
export { ProtectedComponent, RequirePermission } from './ProtectedComponent'
export { permissionGranted } from './permissions'

// Enterprise Authorization Middleware (Phase 4.3.6 §32, §33).
export * from './middleware'
