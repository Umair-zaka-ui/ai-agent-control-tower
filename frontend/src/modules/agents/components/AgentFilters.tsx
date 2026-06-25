import { Select } from '@/components/ui/select'
import type { AgentStatus, RiskLevel } from '../types'
import { AGENT_STATUSES, AGENT_TYPES, RISK_LEVELS } from '../utils/constants'

export interface AgentFilterValues {
  status?: AgentStatus
  agent_type?: string
  risk_level?: RiskLevel
}

interface AgentFiltersProps {
  value: AgentFilterValues
  onChange: (next: AgentFilterValues) => void
}

/** Status / type / risk-level filter row for the agents table. */
export function AgentFilters({ value, onChange }: AgentFiltersProps) {
  return (
    <div className="flex flex-wrap gap-2">
      <Select
        aria-label="Filter by status"
        className="w-40"
        placeholder="All statuses"
        value={value.status ?? ''}
        options={AGENT_STATUSES}
        onChange={(e) =>
          onChange({ ...value, status: (e.target.value || undefined) as AgentStatus | undefined })
        }
      />
      <Select
        aria-label="Filter by type"
        className="w-40"
        placeholder="All types"
        value={value.agent_type ?? ''}
        options={AGENT_TYPES}
        onChange={(e) => onChange({ ...value, agent_type: e.target.value || undefined })}
      />
      <Select
        aria-label="Filter by risk level"
        className="w-40"
        placeholder="All risk levels"
        value={value.risk_level ?? ''}
        options={RISK_LEVELS}
        onChange={(e) =>
          onChange({ ...value, risk_level: (e.target.value || undefined) as RiskLevel | undefined })
        }
      />
    </div>
  )
}
