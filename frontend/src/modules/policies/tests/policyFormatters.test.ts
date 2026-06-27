import { describe, expect, it } from 'vitest'

import { humanizeConditions, summarizeRule } from '../utils/policyFormatters'
import { parseConditions } from '../utils/policyValidators'

describe('humanizeConditions', () => {
  it('turns operator keys into readable clauses', () => {
    expect(humanizeConditions({ amount_gt: 10000, risk_score_gte: 70 })).toEqual([
      'amount is greater than 10000',
      'risk score is at least 70',
    ])
  })

  it('explains the empty case', () => {
    expect(humanizeConditions({})).toEqual(['Always matches (no conditions).'])
  })
})

describe('summarizeRule', () => {
  it('produces a one-line plain-English summary', () => {
    expect(summarizeRule({ amount_gt: 10000 }, 'PENDING_APPROVAL')).toBe(
      'If amount is greater than 10000, then require human approval.',
    )
  })
})

describe('parseConditions', () => {
  it('accepts a valid JSON object', () => {
    expect(parseConditions('{"amount_gt": 5}')).toEqual({ ok: true, value: { amount_gt: 5 } })
  })

  it('treats empty input as no conditions', () => {
    expect(parseConditions('  ')).toEqual({ ok: true, value: {} })
  })

  it('rejects arrays and invalid JSON', () => {
    expect(parseConditions('[1,2]').ok).toBe(false)
    expect(parseConditions('{bad').ok).toBe(false)
  })
})
