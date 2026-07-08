import { describe, expect, it } from 'vitest'

import { toApiError } from '../apiClient'

/**
 * The backend's error envelope is:
 *
 *     { "success": false, "error": { "code": "...", "message": "..." }, "request_id": null }
 *
 * `code` is the *machine-readable* half. Dropping it forces every page to pattern-match
 * on prose, which breaks the moment a message is reworded — and it made the entire
 * invitation/verification error UX (SRS 4.2.2.3.1 §18) unreachable: `InvitationExpiredPage`
 * could never be routed to, and an already-verified email rendered as a failure.
 *
 * These tests describe the *real* wire format, not a mock of it.
 */
const axiosError = (status: number, data: unknown, message = 'Request failed') =>
  ({ response: { status, data }, message }) as never

describe('toApiError — identity error envelope', () => {
  it('extracts the machine-readable code', () => {
    const error = toApiError(
      axiosError(410, {
        success: false,
        error: { code: 'INVITATION_EXPIRED', message: 'This invitation has expired.' },
        request_id: null,
      }),
    )
    expect(error.code).toBe('INVITATION_EXPIRED')
    expect(error.status).toBe(410)
    expect(error.message).toBe('This invitation has expired.')
  })

  it('extracts the code from a 429 with Retry-After semantics', () => {
    const error = toApiError(
      axiosError(429, {
        success: false,
        error: { code: 'RATE_LIMIT_EXCEEDED', message: 'Too many requests.' },
      }),
    )
    expect(error.code).toBe('RATE_LIMIT_EXCEEDED')
  })
})

describe('toApiError — other shapes must keep working', () => {
  it('handles FastAPI\'s plain `detail` string (legacy routes)', () => {
    const error = toApiError(axiosError(404, { detail: 'Not Found' }))
    expect(error.message).toBe('Not Found')
    expect(error.code).toBeUndefined()
    expect(error.detail).toBe('Not Found')
  })

  it('handles a 422 validation body without inventing a code', () => {
    const error = toApiError(
      axiosError(422, { detail: [{ loc: ['body', 'first_name'], msg: 'must not be blank' }] }),
    )
    expect(error.status).toBe(422)
    expect(error.code).toBeUndefined()
  })

  it('handles a network failure with no response at all', () => {
    const error = toApiError({ message: 'Network Error' } as never)
    expect(error.status).toBe(0)
    expect(error.message).toBe('Network Error')
    expect(error.code).toBeUndefined()
  })

  it('ignores a non-string code rather than trusting it', () => {
    const error = toApiError(axiosError(400, { error: { code: 42, message: 'x' } }))
    expect(error.code).toBeUndefined()
  })
})
