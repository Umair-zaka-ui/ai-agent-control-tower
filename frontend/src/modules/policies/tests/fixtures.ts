import type { Policy } from '../types'

/** A representative policy used across the policies module tests. */
export const policyFixture: Policy = {
  id: 'p1a2b3c4-0000-0000-0000-000000000000',
  organization_id: 'org',
  name: 'Large Claim Approval',
  description: 'Route big claims for human review.',
  resource: 'CLAIM',
  action: 'SUBMIT_CLAIM',
  conditions: { amount_gt: 10000, risk_score_gt: 70 },
  decision: 'PENDING_APPROVAL',
  priority: 50,
  enabled: true,
  severity: 'HIGH',
  status: 'ENABLED',
  trigger_count: 3,
  last_triggered_at: '2026-06-25T10:00:00Z',
  created_by: 'user',
  created_at: '2026-06-20T10:00:00Z',
  updated_at: '2026-06-25T10:00:00Z',
}
