import type {
  AuditComplianceSummary,
  AuditEventDetail,
  AuditEventListItem,
  AuditSecuritySummary,
  AuditStatistics,
  AuditTimelineItem,
} from '../types'

export const auditRowFixture: AuditEventListItem = {
  id: '11111111-1111-1111-1111-111111111111',
  created_at: '2026-06-30T09:12:00Z',
  event_type: 'AGENT_ACTION_DECISION',
  category: 'AGENT',
  actor_type: 'AGENT',
  actor_id: '22222222-2222-2222-2222-222222222222',
  actor_name: 'BillingAgent',
  resource: 'CLAIM',
  action: 'SUBMIT_CLAIM',
  decision: 'BLOCK',
  severity: 'HIGH',
  status: 'Blocked',
  entity_type: 'agent_action',
  entity_id: '33333333-3333-3333-3333-333333333333',
  request_id: 'req-abc123',
}

export const auditLoginRowFixture: AuditEventListItem = {
  id: '44444444-4444-4444-4444-444444444444',
  created_at: '2026-06-30T09:00:00Z',
  event_type: 'AUTH_LOGIN',
  category: 'AUTHENTICATION',
  actor_type: 'USER',
  actor_id: '55555555-5555-5555-5555-555555555555',
  actor_name: 'Jane Reviewer',
  resource: null,
  action: null,
  decision: null,
  severity: 'INFO',
  status: 'Recorded',
  entity_type: 'user',
  entity_id: '55555555-5555-5555-5555-555555555555',
  request_id: 'req-login-1',
}

export const auditDetailFixture: AuditEventDetail = {
  ...auditRowFixture,
  correlation_id: 'trace-xyz',
  session_id: 'req-abc123',
  ip_address: '203.0.113.7',
  user_agent: 'Mozilla/5.0',
  reason: 'Agent lacks DELETE permission on CLAIM',
  policy: 'Large Claim Approval',
  approval_id: null,
  risk_score: 88,
  metadata: { decision_reason: 'Agent lacks DELETE permission on CLAIM' },
  request_payload: { amount: 9000 },
  response_payload: { decision: 'BLOCK' },
  related_events: [
    {
      id: auditLoginRowFixture.id,
      event_type: 'AUTH_LOGIN',
      actor_name: 'Jane Reviewer',
      created_at: '2026-06-30T09:00:00Z',
      severity: 'INFO',
    },
    {
      id: auditRowFixture.id,
      event_type: 'AGENT_ACTION_DECISION',
      actor_name: 'BillingAgent',
      created_at: '2026-06-30T09:12:00Z',
      severity: 'HIGH',
    },
  ],
}

export const auditStatisticsFixture: AuditStatistics = {
  total_events: 128,
  security_events: 4,
  policy_evaluations: 22,
  approval_events: 9,
  authentication_events: 31,
  configuration_changes: 12,
}

export const auditTimelineFixture: AuditTimelineItem[] = [
  {
    id: auditRowFixture.id,
    created_at: '2026-06-30T09:12:00Z',
    event_type: 'AGENT_ACTION_DECISION',
    severity: 'HIGH',
    actor_name: 'BillingAgent',
    label: 'BillingAgent Submit Claim on CLAIM → BLOCK',
  },
]

export const auditSecurityFixture: AuditSecuritySummary = {
  failed_logins: 3,
  blocked_agents: 1,
  disabled_api_keys: 0,
  permission_violations: 2,
  suspicious_activity: 1,
  critical_alerts: 0,
  recent: [auditRowFixture],
}

const metric = (label: string, score: number, status: string) => ({
  label,
  score,
  status,
  detail: `${label} detail`,
})

export const auditComplianceFixture: AuditComplianceSummary = {
  hipaa_readiness: metric('HIPAA Readiness', 90, 'Ready'),
  soc2_readiness: metric('SOC 2 Readiness', 75, 'In progress'),
  iso27001_controls: metric('ISO 27001 Controls', 40, 'Attention'),
  policy_coverage: metric('Policy Coverage', 80, 'Ready'),
  approval_coverage: metric('Approval Coverage', 100, 'Ready'),
  audit_completeness: metric('Audit Completeness', 100, 'Ready'),
}
