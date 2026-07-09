/**
 * Standard response envelope (backend SRS §5).
 *
 * The API wraps successful bodies as
 *   `{ success: true, data: <payload>, meta: { request_id, timestamp } }`.
 * The whole frontend is written against the *inner* payload, so we unwrap the
 * envelope in exactly one place per axios instance (the response interceptor and
 * the bare refresh client) and every service stays oblivious to it.
 *
 * Detection is strict — `success === true` plus both `data` and `meta` present — so
 * a legitimate payload that merely happens to have a `data` field is never mistaken
 * for an envelope. Anything that is not an envelope (legacy routes, or the envelope
 * disabled server-side) passes through untouched.
 */
interface SuccessEnvelope<T> {
  success: true
  data: T
  meta: { request_id: string | null; timestamp: string }
}

function isSuccessEnvelope(body: unknown): body is SuccessEnvelope<unknown> {
  return (
    typeof body === 'object' &&
    body !== null &&
    (body as Record<string, unknown>).success === true &&
    'data' in body &&
    'meta' in body
  )
}

/** Return the inner payload if `body` is a success envelope, else `body` unchanged. */
export function unwrapEnvelope<T = unknown>(body: T): T {
  return isSuccessEnvelope(body) ? (body.data as T) : body
}
