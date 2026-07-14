import type { ID, ISODateString } from './common'

/** Resource-based authorization (Phase 4.3.4). */

export type VisibilityLevel =
  | 'PRIVATE'
  | 'TEAM'
  | 'DEPARTMENT'
  | 'ORGANIZATION'
  | 'PUBLIC_INTERNAL'

export type OwnerType = 'USER' | 'TEAM' | 'DEPARTMENT' | 'ORGANIZATION' | 'SERVICE_ACCOUNT'
export type PrincipalType = OwnerType | 'ROLE'
export type ACLEffect = 'ALLOW' | 'DENY'
export type ShareAccessLevel = 'READ' | 'COMMENT' | 'EXECUTE' | 'EDIT' | 'MANAGE'

/** A rule inside a resource policy (§14). */
export interface ResourcePolicyRule {
  permission: string
  principal_type?: PrincipalType
  principal_id?: ID
}

export interface ProtectedResource {
  id: ID
  resource_type: string
  resource_id: ID
  name: string | null
  organization_id: ID
  project_id: ID | null
  owner_id: ID
  owner_type: OwnerType
  created_by: ID | null
  visibility: VisibilityLevel
  status: string
  policy: ResourcePolicyRule[] | null
  created_at: ISODateString | null
  updated_at: ISODateString | null
}

export interface ResourceACLEntry {
  id: ID
  resource_id: ID
  principal_type: PrincipalType
  principal_id: ID
  permission: string
  effect: ACLEffect
  expires_at: ISODateString | null
  created_by: ID | null
  created_at: ISODateString | null
}

export interface ResourceShare {
  id: ID
  resource_id: ID
  shared_with_type: PrincipalType
  shared_with_id: ID
  access_level: ShareAccessLevel
  expires_at: ISODateString | null
  created_by: ID | null
  created_at: ISODateString | null
}

export interface OwnershipHistoryEntry {
  id: ID
  resource_id: ID
  previous_owner: ID | null
  previous_owner_type: OwnerType | null
  new_owner: ID
  new_owner_type: OwnerType
  changed_by: ID | null
  reason: string | null
  created_at: ISODateString | null
}

export interface ResourceDelegation {
  id: ID
  resource_id: ID
  delegate_id: ID
  permissions: string[]
  expires_at: ISODateString | null
  status: 'ACTIVE' | 'REVOKED'
  reason: string | null
  approved_by: ID | null
  created_by: ID | null
  created_at: ISODateString | null
}

/** The full decision the inspector renders (§21). */
export interface ResourceAuthorizeResult {
  allowed: boolean
  permission: string
  reason: string
  source: string
  error_code: string | null
  resource_pk: ID | null
  resource_type: string | null
  owner_id: ID | null
  owner_type: OwnerType | null
  visibility: VisibilityLevel | null
  scope: string | null
  source_role: string | null
  matched_rule_id: ID | null
  steps: string[]
}
