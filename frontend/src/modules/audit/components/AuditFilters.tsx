import { Input } from '@/components/ui/input'
import { Select, type SelectOption } from '@/components/ui/select'
import type { AuditActorType, AuditSeverity } from '../types'
import {
  ACTOR_TYPE_OPTIONS,
  CATEGORY_OPTIONS,
  DECISION_OPTIONS,
  SEVERITY_OPTIONS,
} from '../utils/constants'

export interface AuditFilterValues {
  event_type?: string
  category?: string
  actor_type?: AuditActorType
  severity?: AuditSeverity
  decision?: string
  date_from?: string
  date_to?: string
}

interface AuditFiltersProps {
  value: AuditFilterValues
  onChange: (next: AuditFilterValues) => void
  /** Event-type options sourced from the catalog (GET /audit/events). */
  eventTypeOptions?: SelectOption[]
}

/** Filter bar for the audit explorer (SRS §Filters). */
export function AuditFilters({ value, onChange, eventTypeOptions = [] }: AuditFiltersProps) {
  const set = (patch: Partial<AuditFilterValues>) => onChange({ ...value, ...patch })
  const clean = (v: string) => v || undefined

  return (
    <div className="flex flex-wrap gap-2">
      <Select
        aria-label="Filter by event type"
        className="w-44"
        placeholder="All event types"
        value={value.event_type ?? ''}
        options={eventTypeOptions}
        onChange={(e) => set({ event_type: clean(e.target.value) })}
      />
      <Select
        aria-label="Filter by category"
        className="w-40"
        placeholder="All categories"
        value={value.category ?? ''}
        options={CATEGORY_OPTIONS}
        onChange={(e) => set({ category: clean(e.target.value) })}
      />
      <Select
        aria-label="Filter by actor type"
        className="w-36"
        placeholder="All actors"
        value={value.actor_type ?? ''}
        options={ACTOR_TYPE_OPTIONS}
        onChange={(e) => set({ actor_type: clean(e.target.value) as AuditActorType | undefined })}
      />
      <Select
        aria-label="Filter by severity"
        className="w-36"
        placeholder="All severities"
        value={value.severity ?? ''}
        options={SEVERITY_OPTIONS}
        onChange={(e) => set({ severity: clean(e.target.value) as AuditSeverity | undefined })}
      />
      <Select
        aria-label="Filter by decision"
        className="w-40"
        placeholder="All decisions"
        value={value.decision ?? ''}
        options={DECISION_OPTIONS}
        onChange={(e) => set({ decision: clean(e.target.value) })}
      />
      <Input
        type="date"
        aria-label="From date"
        className="w-40"
        value={value.date_from ?? ''}
        onChange={(e) => set({ date_from: clean(e.target.value) })}
      />
      <Input
        type="date"
        aria-label="To date"
        className="w-40"
        value={value.date_to ?? ''}
        onChange={(e) => set({ date_to: clean(e.target.value) })}
      />
    </div>
  )
}
