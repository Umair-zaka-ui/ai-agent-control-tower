import type {
  AuthorizationAuditEntry,
  ID,
  Permission,
  PermissionGroup,
  PermissionWrite,
  Role,
  RoleAssignment,
  RoleAssignmentWrite,
  RoleEffectivePermissions,
  RoleHierarchyEdge,
  RoleUpdate,
  RoleWrite,
} from '@/types'
import { apiClient } from './apiClient'

/**
 * Enterprise Authorization Platform API (Phase 4.3.1, mounted at /api/v1).
 * Reads need `role.view`; role/permission/hierarchy writes need `role.manage`;
 * assignments need `role.assign`. Every call is re-authorized server-side.
 */
export const authorizationService = {
  // --- Roles --- //
  async listRoles(params: { category?: string; status?: string; search?: string } = {}): Promise<Role[]> {
    const q = new URLSearchParams()
    if (params.category) q.set('category', params.category)
    if (params.status) q.set('status', params.status)
    if (params.search) q.set('search', params.search)
    const suffix = q.toString() ? `?${q}` : ''
    const { data } = await apiClient.get<Role[]>(`/api/v1/roles${suffix}`)
    return data
  },
  async getRole(id: ID): Promise<Role> {
    const { data } = await apiClient.get<Role>(`/api/v1/roles/${id}`)
    return data
  },
  async createRole(payload: RoleWrite): Promise<Role> {
    const { data } = await apiClient.post<Role>('/api/v1/roles', payload)
    return data
  },
  async updateRole(id: ID, payload: RoleUpdate): Promise<Role> {
    const { data } = await apiClient.put<Role>(`/api/v1/roles/${id}`, payload)
    return data
  },
  async deleteRole(id: ID): Promise<void> {
    await apiClient.delete(`/api/v1/roles/${id}`)
  },
  async effectivePermissions(id: ID): Promise<RoleEffectivePermissions> {
    const { data } = await apiClient.get<RoleEffectivePermissions>(
      `/api/v1/roles/${id}/effective-permissions`,
    )
    return data
  },

  // --- Permissions & groups --- //
  async listPermissions(params: { groupId?: ID; search?: string } = {}): Promise<Permission[]> {
    const q = new URLSearchParams()
    if (params.groupId) q.set('group_id', params.groupId)
    if (params.search) q.set('search', params.search)
    const suffix = q.toString() ? `?${q}` : ''
    const { data } = await apiClient.get<Permission[]>(`/api/v1/permissions${suffix}`)
    return data
  },
  async createPermission(payload: PermissionWrite): Promise<Permission> {
    const { data } = await apiClient.post<Permission>('/api/v1/permissions', payload)
    return data
  },
  async deletePermission(id: ID): Promise<void> {
    await apiClient.delete(`/api/v1/permissions/${id}`)
  },
  async listPermissionGroups(): Promise<PermissionGroup[]> {
    const { data } = await apiClient.get<PermissionGroup[]>('/api/v1/permission-groups')
    return data
  },

  // --- Assignments --- //
  async listAssignments(params: { userId?: ID; roleId?: ID } = {}): Promise<RoleAssignment[]> {
    const q = new URLSearchParams()
    if (params.userId) q.set('user_id', params.userId)
    if (params.roleId) q.set('role_id', params.roleId)
    const suffix = q.toString() ? `?${q}` : ''
    const { data } = await apiClient.get<RoleAssignment[]>(`/api/v1/role-assignments${suffix}`)
    return data
  },
  async createAssignment(payload: RoleAssignmentWrite): Promise<RoleAssignment> {
    const { data } = await apiClient.post<RoleAssignment>('/api/v1/role-assignments', payload)
    return data
  },
  async deleteAssignment(id: ID): Promise<void> {
    await apiClient.delete(`/api/v1/role-assignments/${id}`)
  },

  // --- Hierarchy --- //
  async listHierarchy(): Promise<RoleHierarchyEdge[]> {
    const { data } = await apiClient.get<RoleHierarchyEdge[]>('/api/v1/role-hierarchy')
    return data
  },
  async createHierarchyEdge(parent_role_id: ID, child_role_id: ID): Promise<RoleHierarchyEdge> {
    const { data } = await apiClient.post<RoleHierarchyEdge>('/api/v1/role-hierarchy', {
      parent_role_id,
      child_role_id,
    })
    return data
  },
  async deleteHierarchyEdge(id: ID): Promise<void> {
    await apiClient.delete(`/api/v1/role-hierarchy/${id}`)
  },

  // --- Audit --- //
  async audit(params: { eventType?: string; limit?: number } = {}): Promise<AuthorizationAuditEntry[]> {
    const q = new URLSearchParams()
    if (params.eventType) q.set('event_type', params.eventType)
    q.set('limit', String(params.limit ?? 100))
    const { data } = await apiClient.get<AuthorizationAuditEntry[]>(
      `/api/v1/authorization/audit?${q}`,
    )
    return data
  },
}
