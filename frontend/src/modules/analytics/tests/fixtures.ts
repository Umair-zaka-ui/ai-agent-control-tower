import type { AgentAction } from '@/types'
import type { FleetHealth, Insight, KpiMetric } from '../types'

export const kpisFixture: KpiMetric[] = [
  { key: 'total_agents', label: 'Total AI Agents', value: 12, unit: '', change_pct: null, direction: 'flat', positive_is_good: true, estimated: false },
  { key: 'actions_today', label: 'AI Actions Today', value: 48, unit: '', change_pct: 20, direction: 'up', positive_is_good: true, estimated: false },
  { key: 'failure_rate', label: 'AI Failure Rate', value: 8.5, unit: '%', change_pct: 12, direction: 'up', positive_is_good: false, estimated: false },
  { key: 'avg_decision_time', label: 'Avg Decision Time', value: 240, unit: 'ms', change_pct: null, direction: 'flat', positive_is_good: false, estimated: true },
]

export const fleetFixture: FleetHealth = {
  total: 12,
  healthy: 8,
  warning: 2,
  offline: 1,
  active: 9,
  inactive: 1,
  suspended: 1,
  archived: 0,
  blocked: 1,
}

export const insightsFixture: Insight[] = [
  { id: 'approval_volume', title: 'Approval volume increased 18% this week', detail: '12 vs 10 last week.', tone: 'negative', metric: '18%' },
  { id: 'risk_movement', title: 'Average organizational AI risk decreased by 12%', detail: '44 vs 50.', tone: 'positive', metric: '12%' },
]

export const activityFeedFixture: AgentAction[] = [
  {
    id: 'a1',
    agent_id: 'ag1',
    resource: 'CLAIM',
    action: 'SUBMIT_CLAIM',
    input_payload: {},
    decision: 'PENDING_APPROVAL',
    risk_score: 75,
    decision_reason: 'requires approval',
    status: 'CREATED',
    created_at: '2026-06-30T09:42:00Z',
  },
  {
    id: 'a2',
    agent_id: 'ag1',
    resource: 'CLAIM',
    action: 'DELETE',
    input_payload: {},
    decision: 'BLOCK',
    risk_score: 90,
    decision_reason: 'no permission',
    status: 'BLOCKED',
    created_at: '2026-06-30T09:44:00Z',
  },
]
