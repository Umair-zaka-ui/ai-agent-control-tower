import type { ID, ISODateString } from './common'

/** Enterprise organization authorization hierarchy (Phase 4.3.3). */

export type OrgEntityStatus = 'ACTIVE' | 'ARCHIVED'
export type HierarchyLevel =
  | 'ORGANIZATION'
  | 'BUSINESS_UNIT'
  | 'DEPARTMENT'
  | 'TEAM'
  | 'PROJECT'

export interface OrganizationEntity {
  id: ID
  name: string
  slug: string | null
  status: string
  owner_id: ID | null
  created_at: ISODateString | null
}

export interface BusinessUnit {
  id: ID
  organization_id: ID
  name: string
  manager_id: ID | null
  status: string
}

export interface Department {
  id: ID
  organization_id: ID
  business_unit_id: ID | null
  name: string
  manager_id: ID | null
  status: string
}

export interface Team {
  id: ID
  department_id: ID
  name: string
  lead_id: ID | null
  status: string
}

export interface Project {
  id: ID
  team_id: ID
  name: string
  owner_id: ID | null
  status: string
}

export interface ResourceOwnership {
  id: ID
  resource_type: string
  resource_id: ID
  organization_id: ID
  business_unit_id: ID | null
  department_id: ID | null
  team_id: ID | null
  project_id: ID | null
  owner_id: ID | null
}

export interface Delegation {
  id: ID
  organization_id: ID
  delegator_id: ID | null
  delegatee_id: ID
  scope_type: string
  scope_id: ID | null
  permission: string | null
  created_at: ISODateString | null
  revoked_at: ISODateString | null
}

/** A node in the hierarchy tree (GET /hierarchy/tree). */
export interface HierarchyNode {
  id: ID
  name: string
  level: HierarchyLevel
  business_unit_id?: ID | null
  children: HierarchyNode[]
}
