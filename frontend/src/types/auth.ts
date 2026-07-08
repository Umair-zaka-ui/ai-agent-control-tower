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
  refresh_token: string
  token_type: string
  /** Access-token lifetime in seconds (drives silent refresh, SRS §20). */
  expires_in: number
  user?: User | null
  /** Set when the login requires a second factor (SRS §24). */
  mfa_required?: boolean
  mfa_challenge_token?: string | null
}

/** Response of GET /api/v1/auth/me (SRS §16). */
export interface MeResponse {
  user: User
  roles: string[]
  permissions: string[]
  assurance_level: string
  session_id: string | null
}

/** Effective permission codes from the RBAC layer (GET /rbac/me). */
export interface EffectivePermissions {
  permissions: string[]
}
