import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import type { PolicyDecision } from '../types'
import { APPROVAL_PRIORITIES, POLICY_DECISIONS } from '../utils/constants'

interface PolicyActionSelectorProps {
  decision: PolicyDecision
  onDecisionChange: (decision: PolicyDecision) => void
  priority: string
  onPriorityChange: (priority: string) => void
}

/**
 * Decision selector. When PENDING_APPROVAL is chosen, an approval-priority
 * selector appears (SRS §Step 5).
 */
export function PolicyActionSelector({
  decision,
  onDecisionChange,
  priority,
  onPriorityChange,
}: PolicyActionSelectorProps) {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="decision">Decision</Label>
        <Select
          id="decision"
          value={decision}
          options={POLICY_DECISIONS}
          onChange={(e) => onDecisionChange(e.target.value as PolicyDecision)}
        />
      </div>

      {decision === 'PENDING_APPROVAL' && (
        <div className="space-y-2">
          <Label htmlFor="priority">Approval Priority</Label>
          <Select
            id="priority"
            value={priority}
            options={APPROVAL_PRIORITIES.map((p) => ({ value: p, label: p }))}
            onChange={(e) => onPriorityChange(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Indicates how urgently a routed approval should be reviewed.
          </p>
        </div>
      )}
    </div>
  )
}
