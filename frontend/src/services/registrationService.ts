import type {
  EmailDeliveryStatus,
  ID,
  Invitation,
  InvitationCreateRequest,
  InvitationPreview,
  RegisterFromInvitationRequest,
  RegistrationResponse,
} from '@/types'
import { apiClient } from './apiClient'

/**
 * Public onboarding API (Part 4.2.2.3.1 §15).
 *
 * All four endpoints are unauthenticated and rate limited server-side (5 req/min/IP).
 * None of them returns a token: registration does not sign you in, because §12
 * requires the email address to be verified before the account is activated.
 */
export const registrationService = {
  /** Preview an invitation before accepting it. 404/410 carry the *specific* reason. */
  async previewInvitation(token: string): Promise<InvitationPreview> {
    const { data } = await apiClient.get<InvitationPreview>(
      `/api/v1/identity/invitations/${encodeURIComponent(token)}`,
    )
    return data
  },

  /** Accept an invitation: set a password and create the account. */
  async registerFromInvitation(
    payload: RegisterFromInvitationRequest,
  ): Promise<RegistrationResponse> {
    const { data } = await apiClient.post<RegistrationResponse>('/api/v1/auth/register', payload)
    return data
  },

  /** Redeem a single-use verification token. Activates the account. */
  async verifyEmail(token: string): Promise<RegistrationResponse> {
    const { data } = await apiClient.post<RegistrationResponse>('/api/v1/auth/verify-email', {
      token,
    })
    return data
  },

  /**
   * Ask for a new verification link.
   *
   * The server answers identically for a known address, an unknown one and an
   * already-verified one (§14) — so the UI must not imply that a success message
   * means the account exists.
   */
  async resendVerification(email: string): Promise<{ message: string }> {
    const { data } = await apiClient.post<{ message: string }>(
      '/api/v1/auth/resend-verification',
      { email },
    )
    return data
  },
}

/**
 * Administrative invitation management (§15). Requires `invitation.view` /
 * `invitation.manage`; the backend re-checks both on every call.
 */
export const invitationService = {
  async list(status?: string): Promise<Invitation[]> {
    const query = status ? `?status=${encodeURIComponent(status)}` : ''
    const { data } = await apiClient.get<Invitation[]>(`/api/v1/identity/invitations${query}`)
    return data
  },

  async create(payload: InvitationCreateRequest): Promise<Invitation> {
    const { data } = await apiClient.post<Invitation>('/api/v1/identity/invitations', payload)
    return data
  },

  /** Rotates the token: the previous link stops working. */
  async resend(invitationId: ID): Promise<Invitation> {
    const { data } = await apiClient.post<Invitation>('/api/v1/identity/invitations/resend', {
      invitation_id: invitationId,
    })
    return data
  },

  async cancel(invitationId: ID): Promise<Invitation> {
    const { data } = await apiClient.post<Invitation>('/api/v1/identity/invitations/cancel', {
      invitation_id: invitationId,
    })
    return data
  },

  /**
   * Is email actually being sent?
   *
   * With delivery disabled the invitation is created and its link written to a dev
   * outbox file — no message is dispatched. The panel must say so: a plain "PENDING" row
   * implies mail is in flight, and the invitee waits for ever.
   */
  async emailDeliveryStatus(): Promise<EmailDeliveryStatus> {
    const { data } = await apiClient.get<EmailDeliveryStatus>('/api/v1/identity/email-delivery')
    return data
  },
}
