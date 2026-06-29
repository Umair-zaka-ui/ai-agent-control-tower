import { Select } from '@/components/ui/select'
import type { ApprovalPriority, ApprovalStatus } from '../types'
import { APPROVAL_PRIORITIES, APPROVAL_STATUSES, RISK_RANGES } from '../utils/constants'

export interface ApprovalFilterValues {
  status?: ApprovalStatus
  priority?: ApprovalPriority
  /** One of the RISK_RANGES `value`s (e.g. "61-80"). */
  risk?: string
}

interface ApprovalFiltersProps {
  value: ApprovalFilterValues
  onChange: (next: ApprovalFilterValues) => void
  /** Hide the status filter (e.g. on a single-status board). */
  hideStatus?: boolean
}

export function ApprovalFilters({ value, onChange, hideStatus }: ApprovalFiltersProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {!hideStatus && (
        <Select
          aria-label="Filter by status"
          className="w-36"
          placeholder="All statuses"
          value={value.status ?? ''}
          options={APPROVAL_STATUSES}
          onChange={(e) =>
            onChange({ ...value, status: (e.target.value || undefined) as ApprovalStatus | undefined })
          }
        />
      )}
      <Select
        aria-label="Filter by priority"
        className="w-36"
        placeholder="All priorities"
        value={value.priority ?? ''}
        options={APPROVAL_PRIORITIES}
        onChange={(e) =>
          onChange({ ...value, priority: (e.target.value || undefined) as ApprovalPriority | undefined })
        }
      />
      <Select
        aria-label="Filter by risk"
        className="w-40"
        placeholder="All risk levels"
        value={value.risk ?? ''}
        options={RISK_RANGES.map((r) => ({ value: r.value, label: r.label }))}
        onChange={(e) => onChange({ ...value, risk: e.target.value || undefined })}
      />
    </div>
  )
}
