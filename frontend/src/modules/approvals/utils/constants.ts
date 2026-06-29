import type { SelectOption } from '@/components/ui/select'
import type { ApprovalPriority, ApprovalStatus, EscalationTarget } from '../types'

export const APPROVAL_STATUSES: { value: ApprovalStatus; label: string }[] = [
  { value: 'PENDING', label: 'Pending' },
  { value: 'APPROVED', label: 'Approved' },
  { value: 'REJECTED', label: 'Rejected' },
  { value: 'ESCALATED', label: 'Escalated' },
  { value: 'EXPIRED', label: 'Expired' },
]

export const APPROVAL_PRIORITIES: { value: ApprovalPriority; label: string }[] = [
  { value: 'LOW', label: 'Low' },
  { value: 'MEDIUM', label: 'Medium' },
  { value: 'HIGH', label: 'High' },
  { value: 'CRITICAL', label: 'Critical' },
]

/** Risk buckets surfaced as a filter (SRS §Filters → Risk). */
export const RISK_RANGES: { value: string; label: string; min: number; max: number }[] = [
  { value: '0-30', label: 'Low (0–30)', min: 0, max: 30 },
  { value: '31-60', label: 'Moderate (31–60)', min: 31, max: 60 },
  { value: '61-80', label: 'High (61–80)', min: 61, max: 80 },
  { value: '81-100', label: 'Critical (81–100)', min: 81, max: 100 },
]

export const ESCALATION_TARGETS: { value: EscalationTarget; label: string }[] = [
  { value: 'REVIEWER', label: 'Another Reviewer' },
  { value: 'MANAGER', label: 'Manager' },
  { value: 'COMPLIANCE_OFFICER', label: 'Compliance Officer' },
  { value: 'SECURITY_TEAM', label: 'Security Team' },
]

export const ESCALATION_TARGET_LABELS: Record<string, string> = Object.fromEntries(
  ESCALATION_TARGETS.map((t) => [t.value, t.label]),
)

export const toSelectOptions = (
  items: { value: string; label: string }[],
): SelectOption[] => items.map((i) => ({ value: i.value, label: i.label }))

/** Minimum characters required for a rejection reason (SRS §Reject Dialog). */
export const REJECT_REASON_MIN = 20
