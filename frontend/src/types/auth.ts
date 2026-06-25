import type { Role } from '@/constants/roles'
import type { ID, ISODateString } from './common'

export interface User {
  id: ID
  email: string
  full_name?: string | null
  role: Role
  organization_id: ID
  is_active: boolean
  created_at: ISODateString
}

export interface LoginRequest {
  email: string
  password: string
}

export interface AuthTokenResponse {
  access_token: string
  token_type: string
}

/** Effective permission codes from the RBAC layer (GET /rbac/me). */
export interface EffectivePermissions {
  permissions: string[]
}
