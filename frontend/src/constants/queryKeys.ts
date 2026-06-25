/**
 * Centralised TanStack Query keys. Using factory functions keeps cache keys
 * consistent and makes invalidation predictable across hooks.
 */
export const QUERY_KEYS = {
  auth: {
    me: ['auth', 'me'] as const,
  },
  dashboard: {
    summary: ['dashboard', 'summary'] as const,
    activity: (days: number) => ['dashboard', 'activity', days] as const,
    riskTrend: (days: number) => ['dashboard', 'risk-trend', days] as const,
    recentActions: ['dashboard', 'recent-actions'] as const,
    recentAuditLogs: ['dashboard', 'recent-audit-logs'] as const,
    pendingApprovals: ['dashboard', 'pending-approvals'] as const,
  },
  system: {
    health: ['system', 'health'] as const,
  },
  agents: {
    all: ['agents'] as const,
    detail: (id: string) => ['agents', id] as const,
  },
  policies: {
    all: ['policies'] as const,
    detail: (id: string) => ['policies', id] as const,
  },
  approvals: {
    pending: ['approvals', 'pending'] as const,
    detail: (id: string) => ['approvals', id] as const,
  },
  audit: {
    all: ['audit-logs'] as const,
  },
  users: {
    all: ['users'] as const,
  },
} as const
