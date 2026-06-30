import { describe, expect, it } from 'vitest'

import { auditSearchText, clockTime, humanizeToken } from '../utils/format'
import { canExportAudit, canViewAudit } from '../utils/permissions'
import { auditRowFixture } from './fixtures'

describe('audit format utils', () => {
  it('humanizes SCREAMING_SNAKE tokens', () => {
    expect(humanizeToken('AUTH_LOGIN_FAILED')).toBe('Auth Login Failed')
    expect(humanizeToken(null)).toBe('—')
  })

  it('builds lowercase searchable text from a row', () => {
    const text = auditSearchText(auditRowFixture)
    expect(text).toContain('billingagent')
    expect(text).toContain('claim')
  })

  it('formats a 24h clock label', () => {
    expect(clockTime('2026-06-30T09:12:00Z')).toMatch(/^\d{2}:\d{2}$/)
    expect(clockTime('not-a-date')).toBe('—')
  })
})

describe('audit permissions (role-based visibility)', () => {
  it('gates the dashboard on audit.view', () => {
    expect(canViewAudit(['audit.view'])).toBe(true)
    expect(canViewAudit([])).toBe(false)
  })

  it('gates export / security / compliance on audit.export', () => {
    expect(canExportAudit(['audit.export'])).toBe(true)
    expect(canExportAudit(['audit.view'])).toBe(false)
  })
})
