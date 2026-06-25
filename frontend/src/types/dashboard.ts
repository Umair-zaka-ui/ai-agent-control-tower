import type { AgentAction } from './agentAction'
import type { Approval } from './approval'

export interface DashboardSummary {
  total_agents: number
  active_agents: number
  total_actions: number
  pending_approvals: number
  blocked_actions: number
  high_risk_actions: number
  average_risk_score: number
}

export interface DashboardData {
  summary: DashboardSummary
  recentActions: AgentAction[]
  highRiskActions: AgentAction[]
  pendingApprovals: Approval[]
}
