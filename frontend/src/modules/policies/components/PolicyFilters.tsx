import { Select } from '@/components/ui/select'
import type { PolicyDecision, PolicySeverity, PolicyStatus } from '../types'
import {
  POLICY_DECISIONS,
  POLICY_RESOURCES,
  POLICY_SEVERITIES,
  POLICY_STATUSES,
  toOptions,
} from '../utils/constants'

export interface PolicyFilterValues {
  status?: PolicyStatus
  decision?: PolicyDecision
  severity?: PolicySeverity
  resource?: string
}

interface PolicyFiltersProps {
  value: PolicyFilterValues
  onChange: (next: PolicyFilterValues) => void
}

export function PolicyFilters({ value, onChange }: PolicyFiltersProps) {
  return (
    <div className="flex flex-wrap gap-2">
      <Select
        aria-label="Filter by status"
        className="w-36"
        placeholder="All statuses"
        value={value.status ?? ''}
        options={POLICY_STATUSES}
        onChange={(e) => onChange({ ...value, status: (e.target.value || undefined) as PolicyStatus | undefined })}
      />
      <Select
        aria-label="Filter by decision"
        className="w-40"
        placeholder="All decisions"
        value={value.decision ?? ''}
        options={POLICY_DECISIONS}
        onChange={(e) => onChange({ ...value, decision: (e.target.value || undefined) as PolicyDecision | undefined })}
      />
      <Select
        aria-label="Filter by severity"
        className="w-36"
        placeholder="All severities"
        value={value.severity ?? ''}
        options={POLICY_SEVERITIES}
        onChange={(e) => onChange({ ...value, severity: (e.target.value || undefined) as PolicySeverity | undefined })}
      />
      <Select
        aria-label="Filter by resource"
        className="w-40"
        placeholder="All resources"
        value={value.resource ?? ''}
        options={toOptions(POLICY_RESOURCES)}
        onChange={(e) => onChange({ ...value, resource: e.target.value || undefined })}
      />
    </div>
  )
}
