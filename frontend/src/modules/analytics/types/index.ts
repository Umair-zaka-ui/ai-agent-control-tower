import type { ID, ISODateString } from '@/types'

/** A single executive KPI tile (GET /analytics/kpis). */
export interface KpiMetric {
  key: string
  label: string
  value: number
  unit: string
  change_pct: number | null
  direction: 'up' | 'down' | 'flat'
  positive_is_good: boolean
  estimated: boolean
}

export interface FleetHealth {
  total: number
  healthy: number
  warning: number
  offline: number
  active: number
  inactive: number
  suspended: number
  archived: number
  blocked: number
}

export interface ActivityPoint {
  period: string
  executed: number
  blocked: number
  approvals: number
  rejections: number
  escalations: number
  failures: number
}

export type ActivityRange = 'daily' | 'weekly' | 'monthly' | 'yearly'

export interface RiskBands {
  low: number
  medium: number
  high: number
  critical: number
}

export interface RiskTrendPoint {
  date: string
  risk_score: number
}

export interface RiskGroup {
  label: string
  avg_risk: number
  count: number
}

export interface RiskHeatmapRow {
  label: string
  low: number
  medium: number
  high: number
  critical: number
}

export interface HighRiskAgent {
  agent_id: ID
  name: string | null
  agent_type: string | null
  avg_risk: number
  action_count: number
  health: string
}

export interface RiskAnalytics {
  distribution: RiskBands
  trend: RiskTrendPoint[]
  by_department: RiskGroup[]
  by_agent_type: RiskGroup[]
  heatmap: RiskHeatmapRow[]
  high_risk_agents: HighRiskAgent[]
}

export interface PerformanceMetrics {
  avg_response_time_ms: number
  execution_time_ms: number
  decision_latency_ms: number
  policy_eval_time_ms: number
  approval_delay_seconds: number
  avg_processing_time_ms: number
  failure_rate: number
  retry_rate: number
  estimated: boolean
}

export interface AgentRanking {
  rank: number
  agent_id: ID
  name: string | null
  agent_type: string | null
  requests: number
  success_pct: number
  failures: number
  avg_risk: number
  avg_response_ms: number
  health: string
}

export interface PerformanceAnalytics {
  metrics: PerformanceMetrics
  ranking: AgentRanking[]
}

export interface PolicyStat {
  policy_id: ID
  name: string
  decision: string
  trigger_count: number
  severity: string
  enabled: boolean
}

export interface PolicyAnalytics {
  most_triggered: PolicyStat[]
  least_used: PolicyStat[]
  most_blocking: PolicyStat[]
  most_approval: PolicyStat[]
  total_policies: number
  enabled_policies: number
  effectiveness_pct: number
  false_positive_rate: number
  coverage_pct: number
}

export interface ReviewerStat {
  user_id: ID
  name: string | null
  assigned: number
  reviewed: number
  approved: number
  rejected: number
  avg_review_seconds: number
}

export interface HumanReviewAnalytics {
  avg_approval_time_seconds: number
  pending_queue: number
  escalation_rate: number
  approval_ratio: number
  rejection_ratio: number
  reviewers: ReviewerStat[]
}

export interface CostItem {
  key: string
  label: string
  amount: number
  unit: string
}

export interface CostAnalytics {
  items: CostItem[]
  total: number
  currency: string
  period_label: string
  estimated: boolean
}

export interface Insight {
  id: string
  title: string
  detail: string
  tone: 'positive' | 'negative' | 'neutral'
  metric: string | null
}

export interface ReportRow {
  label: string
  value: string
}

export interface ReportSection {
  title: string
  rows: ReportRow[]
}

export type ReportPeriod = 'daily' | 'weekly' | 'monthly' | 'quarterly' | 'annual'

export interface AnalyticsReport {
  period: string
  label: string
  generated_at: ISODateString
  sections: ReportSection[]
}

export interface AnalyticsOverview {
  generated_at: ISODateString
  kpis: KpiMetric[]
  fleet_health: FleetHealth
  risk_distribution: RiskBands
  activity: ActivityPoint[]
  insights: Insight[]
}
