import type { ID, ISODateString } from '@/types'

/** Canonical identity lifecycle (mirrors the backend IdentityStatus). */
export type IdentityStatus =
  | 'CREATED'
  | 'PENDING_VERIFICATION'
  | 'ACTIVE'
  | 'SUSPENDED'
  | 'DISABLED'
  | 'ARCHIVED'
  | 'DELETED'

/** A human identity (GET /api/v1/identity/users). */
export interface IdentityUser {
  id: ID
  email: string
  display_name: string
  organization_id: ID
  department_id: ID | null
  role: string
  is_active: boolean
  created_at: ISODateString
  updated_at: ISODateString
}

export interface IdentityOrganization {
  id: ID
  name: string
  created_at: ISODateString
}

export interface IdentityDepartment {
  id: ID
  organization_id: ID
  name: string
  manager_id: ID | null
  created_at: ISODateString
}

export interface IdentityRole {
  id: ID
  name: string
  description: string | null
  is_system: boolean
  organization_id: ID | null
}

export interface CreateUserInput {
  email: string
  display_name: string
  password: string
  organization_id: ID
  department_id?: ID
  role?: string
}

/** Standard identity error envelope (SRS §18). */
export interface IdentityErrorEnvelope {
  success: false
  error: { code: string; message: string }
  request_id: string | null
}
