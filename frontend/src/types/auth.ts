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
  /** Extends the ABSOLUTE session ceiling only; idle timeout still applies. */
  remember_me?: boolean
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
  /** Session posture returned on login (Part 4.2.2.2 §15, §25). */
  session_id?: string | null
  security_score?: number
  is_new_device?: boolean
  idle_timeout_seconds?: number | null
  idle_warning_seconds?: number | null
}

/** Lifecycle state of a session (SRS 4.2.2.2 §4). */
export type SessionStatus =
  | 'CREATED'
  | 'ACTIVE'
  | 'IDLE'
  | 'EXPIRED'
  | 'REVOKED'
  | 'SUSPICIOUS'
  | 'TERMINATED'

export type SecurityBand = 'HEALTHY' | 'WARNING' | 'HIGH_RISK'

export type DeviceStatus = 'UNKNOWN' | 'TRUSTED' | 'BLOCKED'

/** One row of GET /api/v1/auth/sessions (SRS §18). */
export interface AuthSession {
  id: ID
  status: SessionStatus
  device_id: ID | null
  device_name: string | null
  device_type: string | null
  browser: string | null
  browser_version: string | null
  operating_system: string | null
  ip_address: string | null
  country: string | null
  city: string | null
  login_method: string | null
  created_at: ISODateString
  last_seen_at: ISODateString | null
  last_activity_at: ISODateString | null
  idle_expires_at: ISODateString
  absolute_expires_at: ISODateString
  revoked_at: ISODateString | null
  revoked_reason: string | null
  security_score: number
  is_trusted: boolean
  /** Derived server-side: powers the "Current Device" badge (SRS §19). */
  is_current: boolean
  security_band: SecurityBand | null
}

/** GET /api/v1/auth/sessions/{id} — adds forensic detail. */
export interface AuthSessionDetail extends AuthSession {
  refresh_token_family_id: ID
  user_agent: string | null
}

/** One row of GET /api/v1/auth/devices (SRS §13). */
export interface AuthDevice {
  id: ID
  device_name: string | null
  device_type: string | null
  browser: string | null
  browser_version: string | null
  operating_system: string | null
  status: DeviceStatus
  last_ip: string | null
  last_seen_at: ISODateString | null
  created_at: ISODateString
  is_current: boolean
}

export interface LogoutResponse {
  revoked_session_ids: ID[]
}

/**
 * One row of the security-event stream (SRS §26).
 *
 * `meta` is the forensic payload, passed through verbatim by the API: revocation
 * reason, the acting administrator, security band, device id, token id. Typed as
 * a permissive record because its shape is per-event-type by design.
 */
export interface SecurityEvent {
  id: ID
  event_type: string
  actor_type: string
  actor_id: ID | null
  target_type: string | null
  target_id: ID | null
  organization_id: ID | null
  request_id: string | null
  correlation_id: string | null
  ip_address: string | null
  meta: Record<string, unknown>
  created_at: ISODateString
}

export interface SecurityEventPage {
  items: SecurityEvent[]
  total: number
  limit: number
  offset: number
}

/** A member of the caller's organization (GET /api/v1/identity/users). */
export interface OrgUser {
  id: ID
  email: string
  display_name: string
  organization_id: ID
  role: string
  is_active: boolean
  status: string
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
