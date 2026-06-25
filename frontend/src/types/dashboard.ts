import type { AgentAction } from './agentAction'
import type { Approval } from './approval'

/** Headline counts (GET /dashboard/summary). */
export interface DashboardSummary {
  agents: number
  active_agents: number
  pending_approvals: number
  blocked_actions: number
  policies: number
  total_actions: number
  today_actions: number
}

/** One day of agent activity (GET /dashboard/activity). */
export interface DashboardActivity {
  date: string
  actions: number
}

/** One day of organizational risk (GET /dashboard/risk-trend). */
export interface RiskTrend {
  date: string
  risk_score: number
}

export type ServiceHealth = 'healthy' | 'warning' | 'offline'

/** Subsystem health (GET /system/health). */
export interface SystemHealth {
  api: ServiceHealth
  database: ServiceHealth
  policy_engine: ServiceHealth
  approval_engine: ServiceHealth
  audit: ServiceHealth
}

/** A recent agent action shown in the dashboard feed. */
export type RecentAction = AgentAction

/** A pending approval shown in the dashboard widget. */
export type PendingApproval = Approval
