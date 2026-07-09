import { describe, expect, it } from 'vitest'

import { unwrapEnvelope } from '../envelope'

/**
 * The backend wraps successful bodies as `{ success, data, meta }` (SRS §5). The
 * frontend unwraps it centrally so every service sees the inner payload. These tests
 * pin the *detection* rules: unwrap a real envelope, and leave everything else alone.
 */
describe('unwrapEnvelope', () => {
  it('returns the inner data for a success envelope', () => {
    const inner = { access_token: 'abc', expires_in: 900 }
    const enveloped = { success: true, data: inner, meta: { request_id: 'r1', timestamp: 't' } }
    expect(unwrapEnvelope(enveloped)).toBe(inner)
  })

  it('unwraps an array payload', () => {
    const inner = [{ id: '1' }, { id: '2' }]
    expect(unwrapEnvelope({ success: true, data: inner, meta: { request_id: null, timestamp: 't' } })).toBe(
      inner,
    )
  })

  it('passes a bare (non-enveloped) object through unchanged', () => {
    const bare = { id: '1', name: 'agent' }
    expect(unwrapEnvelope(bare)).toBe(bare)
  })

  it('does not unwrap a payload that merely has a data field but no meta', () => {
    const looksSimilar = { success: true, data: { x: 1 } }
    expect(unwrapEnvelope(looksSimilar)).toBe(looksSimilar)
  })

  it('does not unwrap an error envelope (success !== true)', () => {
    const errorBody = { success: false, error: { code: 'X' }, meta: { request_id: 'r', timestamp: 't' } }
    expect(unwrapEnvelope(errorBody)).toBe(errorBody)
  })

  it('handles null / primitive bodies', () => {
    expect(unwrapEnvelope(null)).toBeNull()
    expect(unwrapEnvelope('ok')).toBe('ok')
  })
})
