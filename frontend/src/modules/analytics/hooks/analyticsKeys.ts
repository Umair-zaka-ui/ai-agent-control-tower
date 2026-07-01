import type { ActivityRange, ReportPeriod } from '../types'

/** TanStack Query keys for the analytics module. */
export const analyticsKeys = {
  all: ['analytics'] as const,
  overview: ['analytics', 'overview'] as const,
  kpis: ['analytics', 'kpis'] as const,
  activity: (range: ActivityRange) => ['analytics', 'activity', range] as const,
  fleetHealth: ['analytics', 'fleet-health'] as const,
  risk: ['analytics', 'risk'] as const,
  performance: ['analytics', 'performance'] as const,
  policies: ['analytics', 'policies'] as const,
  review: ['analytics', 'review'] as const,
  cost: ['analytics', 'cost'] as const,
  insights: ['analytics', 'insights'] as const,
  report: (period: ReportPeriod) => ['analytics', 'report', period] as const,
  feed: ['analytics', 'feed'] as const,
}

/** Auto-refresh intervals (SRS §Auto Refresh). */
export const REFRESH = {
  dashboard: 15_000,
  feed: 10_000,
  kpis: 30_000,
  charts: 60_000,
} as const
