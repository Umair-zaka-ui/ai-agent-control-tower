import type { ID, ISODateString } from './common'

/** Enterprise Authorization Platform (Phase 4.3.1). */

export type RoleCategory = 'SYSTEM' | 'CUSTOM' | 'ORGANIZATION' | 'PROJECT' | 'RESOURCE'
export type RoleStatus =
  | 'CREATED'
  | 'ACTIVE'
  | 'UPDATED'
  | 'DEPRECATED'
  | 'ARCHIVED'
  | 'DELETED'
export type AssignmentScope =
  | 'GLOBAL'
  | 'ORGANIZATION'
  | 'DEPARTMENT'
  | 'TEAM'
  | 'PROJECT'
  | 'RESOURCE'

export interface Role {
  id: ID
  organization_id: ID | null
  name: string
  display_name: string | null
  description: string | null
  category: RoleCategory
  status: RoleStatus
  is_system: boolean
  is_assignable: boolean
  priority: number
  permissions: string[]
  assignment_count: number | null
  created_at: ISODateString | null
  updated_at: ISODateString | null
}

export interface RoleWrite {
  name: string
  display_name?: string | null
  description?: string | null
  category?: RoleCategory
  priority?: number
  permissions?: string[]
}

export interface RoleUpdate {
  display_name?: string | null
  description?: string | null
  priority?: number | null
  status?: RoleStatus | null
  permissions?: string[] | null
}

export interface Permission {
  id: ID
  code: string
  display_name: string | null
  description: string | null
  group_id: ID | null
  resource_type: string | null
  action: string | null
  is_system: boolean
  created_at: ISODateString | null
}

export interface PermissionWrite {
  code: string
  display_name?: string | null
  description?: string | null
  group_id?: ID | null
}

export interface PermissionGroup {
  id: ID
  name: string
  display_name: string
  description: string | null
  sort_order: number
}

export interface RoleAssignment {
  id: ID
  user_id: ID
  role_id: ID
  scope: AssignmentScope
  organization_id: ID | null
  department_id: ID | null
  team_id: ID | null
  project_id: ID | null
  resource_type: string | null
  resource_id: ID | null
  expires_at: ISODateString | null
  assigned_by: ID | null
  created_at: ISODateString | null
}

export interface RoleAssignmentWrite {
  user_id: ID
  role_id: ID
  scope: AssignmentScope
  department_id?: ID | null
  team_id?: ID | null
  project_id?: ID | null
  resource_type?: string | null
  resource_id?: ID | null
  expires_at?: ISODateString | null
}

export interface RoleHierarchyEdge {
  id: ID
  parent_role_id: ID
  child_role_id: ID
  created_at: ISODateString | null
}

export interface RoleEffectivePermissions {
  role_id: ID
  permissions: string[]
}

export interface AuthorizationAuditEntry {
  id: ID
  organization_id: ID | null
  actor_id: ID | null
  identity_id: ID | null
  event_type: string
  permission: string | null
  resource_type: string | null
  resource_id: ID | null
  decision: string | null
  reason: string | null
  meta: Record<string, unknown> | null
  created_at: ISODateString | null
}
