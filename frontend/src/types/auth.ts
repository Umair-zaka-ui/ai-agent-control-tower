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
  /**
   * Part 4.2.2.3.2 §11/§13: the user must change their password before any feature
   * (expired, or an admin-issued temporary password). The SPA routes to the forced
   * change flow when true.
   */
  password_change_required?: boolean
}

// --- Credential management (Part 4.2.2.3.2) -------------------------------- //
export interface ChangePasswordPayload {
  current_password: string
  new_password: string
  revoke_other_sessions?: boolean | null
}

export interface PasswordPolicy {
  min_length: number
  max_length: number
  require_uppercase: boolean
  require_lowercase: boolean
  require_number: boolean
  require_special: boolean
  allow_spaces: boolean
  forbid_common: boolean
  forbid_sequences: boolean
  forbid_repeats: boolean
  forbid_identity: boolean
  history_depth: number
  max_age_days: number
  min_age_hours: number
  expiry_warning_days: number[]
  temp_password_ttl_hours: number
}

export interface PasswordExpiration {
  expires_at: string | null
  changed_at: string | null
  days_until_expiry: number | null
  is_expired: boolean
  in_warning_window: boolean
  must_change: boolean
  change_required: boolean
}

export interface PasswordStrengthResult {
  level: string
  score: number
  meets_policy: boolean
  entropy_bits: number
  feedback: string | null
}

export interface AdminResetResult {
  user_id: ID
  temporary_password: string
  expires_at: string
  must_change_password: boolean
  message: string
}

export interface PasswordDashboardUser {
  user_id: ID
  name: string
  email: string
  expires_at: string | null
  days_until_expiry: number | null
  is_expired: boolean
  must_change: boolean
}

export interface PasswordDashboard {
  expired: PasswordDashboardUser[]
  expiring_soon: PasswordDashboardUser[]
  temporary: PasswordDashboardUser[]
  must_change: PasswordDashboardUser[]
  total_users: number
}

// --- Recovery (Part 4.2.2.3.3) --------------------------------------------- //
export interface RecoveryAck {
  success: boolean
  message: string
}

export interface ResetPasswordPayload {
  token: string
  new_password: string
}

export interface ChangeEmailPayload {
  new_email: string
  current_password: string
}

export interface RecoveryEvent {
  id: ID
  event_type: string
  actor_id: ID | null
  ip_address: string | null
  user_agent: string | null
  created_at: ISODateString
  metadata: Record<string, unknown> | null
}

// --- Account protection (Part 4.2.2.3.4) ----------------------------------- //
export interface ProtectionSummary {
  failed_logins_today: number
  locked_accounts: number
  high_risk_attempts: number
  blocked_ips: number
  active_rules: number
  risk_events_recent: number
}

export interface LoginAttempt {
  id: ID
  email: string
  success: boolean
  failure_reason: string | null
  ip_address: string | null
  country: string | null
  city: string | null
  user_agent: string | null
  device_fingerprint: string | null
  risk_score: number | null
  decision: string | null
  created_at: ISODateString
}

export interface RiskEvent {
  id: ID
  user_id: ID | null
  event_type: string
  risk_score: number
  risk_level: string
  signals: Record<string, unknown>
  decision: string
  ip_address: string | null
  user_agent: string | null
  created_at: ISODateString
}

export interface AccountLock {
  id: ID
  user_id: ID
  organization_id: ID
  reason: string
  status: string
  locked_at: ISODateString
  expires_at: ISODateString | null
  unlocked_at: ISODateString | null
  unlocked_by: ID | null
  meta: Record<string, unknown>
  created_at: ISODateString
  user_email: string | null
  risk_score: number | null
}

export interface BlockedIp {
  id: ID
  organization_id: ID | null
  ip_address: string
  reason: string | null
  expires_at: ISODateString | null
  created_by: ID | null
  created_at: ISODateString
}

export interface ProtectionRuleCondition {
  field: string
  op: string
  value?: unknown
}

export interface ProtectionRule {
  id: ID
  organization_id: ID
  name: string
  description: string | null
  conditions: ProtectionRuleCondition[]
  decision: string
  enabled: boolean
  priority: number
  created_at: ISODateString
  updated_at: ISODateString
}

export interface ProtectionRuleWrite {
  name: string
  description?: string | null
  conditions: ProtectionRuleCondition[]
  decision: string
  enabled?: boolean
  priority?: number
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

// --------------------------------------------------------------------------- //
// Registration, invitations & email verification (Part 4.2.2.3.1)
// --------------------------------------------------------------------------- //

export type InvitationStatus = 'PENDING' | 'ACCEPTED' | 'EXPIRED' | 'CANCELLED'

export type RegistrationMode = 'INVITE_ONLY' | 'ADMIN_ONLY' | 'SELF_SERVICE'

/** Admin view of an invitation. Carries no token — not even a prefix. */
export interface Invitation {
  id: ID
  organization_id: ID
  email: string
  role_id: ID | null
  department_id: ID | null
  team_id: ID | null
  invited_by: ID | null
  status: InvitationStatus
  expires_at: ISODateString
  accepted_at: ISODateString | null
  cancelled_at: ISODateString | null
  resent_count: number
  last_sent_at: ISODateString | null
  created_at: ISODateString
  is_expired: boolean
}

/** Public preview shown on the accept-invitation page (SRS §17). */
export interface InvitationPreview {
  email: string
  organization_name: string
  role_name: string | null
  department_name: string | null
  invited_by_name: string | null
  expires_at: ISODateString
}

/** Whether invitation emails actually leave the building (SRS §6). */
export interface EmailDeliveryStatus {
  enabled: boolean
  /** Where suppressed messages are written when delivery is off. */
  outbox_path: string | null
}

export interface InvitationCreateRequest {
  email: string
  role_id?: ID | null
  department_id?: ID | null
  team_id?: ID | null
}

export interface RegisterFromInvitationRequest {
  token: string
  first_name: string
  last_name: string
  password: string
  confirm_password: string
  phone?: string | null
  timezone?: string | null
  language?: string | null
  job_title?: string | null
}

/** Registration deliberately returns no tokens: you must verify your email first. */
export interface RegistrationResponse {
  email: string
  status: string
  email_sent: boolean
  requires_approval: boolean
  message: string
}
