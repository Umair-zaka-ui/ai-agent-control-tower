import type { AgentCapability, AgentStatus, RiskLevel } from '../types'

export const AGENT_STATUSES: { value: AgentStatus; label: string }[] = [
  { value: 'ACTIVE', label: 'Active' },
  { value: 'INACTIVE', label: 'Inactive' },
  { value: 'SUSPENDED', label: 'Suspended' },
  { value: 'ARCHIVED', label: 'Archived' },
  { value: 'BLOCKED', label: 'Blocked' },
]

export const RISK_LEVELS: { value: RiskLevel; label: string }[] = [
  { value: 'LOW', label: 'Low' },
  { value: 'MEDIUM', label: 'Medium' },
  { value: 'HIGH', label: 'High' },
  { value: 'CRITICAL', label: 'Critical' },
]

/** Suggested agent types (free-text is also allowed on create). */
export const AGENT_TYPES: { value: string; label: string }[] = [
  { value: 'billing', label: 'Billing' },
  { value: 'scheduling', label: 'Scheduling' },
  { value: 'clinical', label: 'Clinical' },
  { value: 'research', label: 'Research' },
  { value: 'custom', label: 'Custom' },
]

export const CAPABILITIES: { value: AgentCapability; label: string }[] = [
  { value: 'read', label: 'Read' },
  { value: 'write', label: 'Write' },
  { value: 'execute', label: 'Execute' },
  { value: 'delete', label: 'Delete' },
  { value: 'external_api', label: 'External API Access' },
  { value: 'database', label: 'Database Access' },
]

export const PAGE_SIZE_OPTIONS = [10, 25, 50, 100] as const
