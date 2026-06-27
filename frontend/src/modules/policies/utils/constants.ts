import type { PolicyDecision, PolicySeverity, PolicyStatus } from '../types'

export const POLICY_RESOURCES = [
  'CLAIM',
  'PATIENT_RECORD',
  'APPOINTMENT',
  'PAYMENT',
  'USER',
  'CUSTOM',
] as const

export const POLICY_ACTIONS = [
  'READ',
  'CREATE',
  'UPDATE',
  'DELETE',
  'SUBMIT_CLAIM',
  'SEND_EMAIL',
  'TRANSFER_MONEY',
  'RECOMMEND_MEDICATION',
] as const

export const POLICY_DECISIONS: { value: PolicyDecision; label: string }[] = [
  { value: 'ALLOW', label: 'Allow' },
  { value: 'BLOCK', label: 'Block' },
  { value: 'PENDING_APPROVAL', label: 'Pending Approval' },
]

export const POLICY_SEVERITIES: { value: PolicySeverity; label: string }[] = [
  { value: 'LOW', label: 'Low' },
  { value: 'MEDIUM', label: 'Medium' },
  { value: 'HIGH', label: 'High' },
  { value: 'CRITICAL', label: 'Critical' },
]

export const POLICY_STATUSES: { value: PolicyStatus; label: string }[] = [
  { value: 'DRAFT', label: 'Draft' },
  { value: 'ENABLED', label: 'Enabled' },
  { value: 'DISABLED', label: 'Disabled' },
  { value: 'ARCHIVED', label: 'Archived' },
]

export const APPROVAL_PRIORITIES = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'] as const

/** Options helper for the resource/action selects. */
export const toOptions = (values: readonly string[]) =>
  values.map((v) => ({ value: v, label: v.replace(/_/g, ' ') }))
