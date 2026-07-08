import type {
  AuthDevice,
  AuthSession,
  AuthSessionDetail,
  AuthTokenResponse,
  ID,
  LoginRequest,
  LogoutResponse,
  MeResponse,
  OrgUser,
  SecurityEvent,
  SecurityEventPage,
} from '@/types'
import { clearAuthStorage } from '@/utils/tokenStorage'
import { apiClient } from './apiClient'
import { refreshAccessToken } from './tokenRefresh'

/**
 * Human authentication + session lifecycle API (mounted at /api/v1/auth).
 * All auth I/O lives here so token handling stays in one place.
 */
export const authService = {
  /** Exchange email + password for an access + refresh token pair (SRS §6). */
  async login(payload: LoginRequest): Promise<AuthTokenResponse> {
    const { data } = await apiClient.post<AuthTokenResponse>('/api/v1/auth/login', payload)
    return data
  },

  /** Current identity, roles and effective permissions (GET /api/v1/auth/me). */
  async getMe(): Promise<MeResponse> {
    const { data } = await apiClient.get<MeResponse>('/api/v1/auth/me')
    return data
  },

  /** Silent/reactive token refresh — returns the new access token or null. */
  refresh: refreshAccessToken,

  /**
   * Server-side logout: revoke the session + refresh-token family (SRS §16),
   * then clear local storage. Best-effort — local state is cleared regardless.
   *
   * As of Part 4.2.2.2 the server revalidates the session on every request, so
   * this genuinely ends the session rather than merely dropping the local token.
   */
  async logout(allDevices = false): Promise<void> {
    try {
      await apiClient.post('/api/v1/auth/logout', { all_devices: allDevices })
    } catch {
      /* already unauthenticated / offline — clear locally anyway */
    }
    clearAuthStorage()
  },
}

/**
 * Session & device management (SRS §17–§19, §23).
 *
 * Kept separate from `authService` because these are ordinary authenticated
 * reads/writes — they belong to the 401-refresh-and-retry path, whereas
 * login/logout/refresh must never trigger it.
 */
export const sessionService = {
  /** Active sessions for the caller; `is_current` marks this device (SRS §19). */
  async listSessions(): Promise<AuthSession[]> {
    const { data } = await apiClient.get<AuthSession[]>('/api/v1/auth/sessions')
    return data
  },

  async getSession(id: ID): Promise<AuthSessionDetail> {
    const { data } = await apiClient.get<AuthSessionDetail>(`/api/v1/auth/sessions/${id}`)
    return data
  },

  /** Force-logout one session (SRS §17). */
  async revokeSession(id: ID, reason?: string): Promise<AuthSession> {
    const { data } = await apiClient.post<AuthSession>(
      `/api/v1/auth/sessions/${id}/revoke`,
      reason ? { reason } : {},
    )
    return data
  },

  /** Revoke every session, including this one (SRS §24 "Logout all devices"). */
  async logoutAllDevices(): Promise<LogoutResponse> {
    const { data } = await apiClient.post<LogoutResponse>('/api/v1/auth/logout', {
      all_devices: true,
    })
    return data
  },

  async listDevices(): Promise<AuthDevice[]> {
    const { data } = await apiClient.get<AuthDevice[]>('/api/v1/auth/devices')
    return data
  },

  async trustDevice(id: ID): Promise<AuthDevice> {
    const { data } = await apiClient.post<AuthDevice>(`/api/v1/auth/devices/${id}/trust`)
    return data
  },

  /** Blocking a device also revokes its live sessions server-side (SRS §14). */
  async blockDevice(id: ID): Promise<AuthDevice> {
    const { data } = await apiClient.post<AuthDevice>(`/api/v1/auth/devices/${id}/block`)
    return data
  },

  /** The caller's own recent security activity. Never another user's (SRS §25). */
  async mySecurityEvents(limit = 25): Promise<SecurityEvent[]> {
    const { data } = await apiClient.get<SecurityEvent[]>(
      `/api/v1/auth/security-events?limit=${limit}`,
    )
    return data
  },
}

/**
 * Administrative session management (SRS §17, §32) — `/api/v1/identity/*`.
 *
 * Requires `session.view` / `session.revoke`. Every call is org-scoped server-side;
 * a target in another organization returns 404, never "exists but not yours".
 */
export const adminSessionService = {
  /** Organization members, for the user picker. Requires `user.view`. */
  async listUsers(): Promise<OrgUser[]> {
    const { data } = await apiClient.get<OrgUser[]>('/api/v1/identity/users')
    return data
  },

  async listUserSessions(userId: ID): Promise<AuthSession[]> {
    const { data } = await apiClient.get<AuthSession[]>(
      `/api/v1/identity/sessions?user_id=${userId}`,
    )
    return data
  },

  async listUserDevices(userId: ID): Promise<AuthDevice[]> {
    const { data } = await apiClient.get<AuthDevice[]>(`/api/v1/identity/users/${userId}/devices`)
    return data
  },

  /** Force-logout one session. Defaults to ADMIN_REVOKED server-side. */
  async revokeSession(sessionId: ID, reason?: string): Promise<AuthSession> {
    const { data } = await apiClient.post<AuthSession>(
      `/api/v1/identity/sessions/${sessionId}/revoke`,
      reason ? { reason } : {},
    )
    return data
  },

  /** Sign a user out of every device. Does not disable the account. */
  async revokeAllSessions(userId: ID, reason?: string): Promise<LogoutResponse> {
    const { data } = await apiClient.post<LogoutResponse>(
      `/api/v1/identity/users/${userId}/sessions/revoke-all`,
      reason ? { reason } : {},
    )
    return data
  },

  /** The organization's security-event stream (DoD §32 "…and audit"). */
  async listSecurityEvents(params: {
    actorId?: ID
    sessionId?: ID
    eventType?: string
    limit?: number
    offset?: number
  } = {}): Promise<SecurityEventPage> {
    const q = new URLSearchParams()
    if (params.actorId) q.set('actor_id', params.actorId)
    if (params.sessionId) q.set('session_id', params.sessionId)
    if (params.eventType) q.set('event_type', params.eventType)
    q.set('limit', String(params.limit ?? 25))
    q.set('offset', String(params.offset ?? 0))
    const { data } = await apiClient.get<SecurityEventPage>(
      `/api/v1/identity/security-events?${q.toString()}`,
    )
    return data
  },

  /** One session's full history, oldest first — "who revoked it, when, why?". */
  async listSessionEvents(sessionId: ID): Promise<SecurityEvent[]> {
    const { data } = await apiClient.get<SecurityEvent[]>(
      `/api/v1/identity/sessions/${sessionId}/events`,
    )
    return data
  },
}
