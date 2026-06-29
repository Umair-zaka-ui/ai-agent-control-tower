import { ShieldCheck, ShieldOff } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { ApprovalPolicyInfo } from '../types'
import { humanizeConditions } from '../utils/conditions'

/** Explains which policy governed the action and why (SRS §Policy Explanation). */
export function PolicyExplanation({ policy }: { policy: ApprovalPolicyInfo }) {
  if (!policy.matched) {
    return (
      <div className="flex items-start gap-3 rounded-md border border-border bg-muted/30 p-3">
        <ShieldOff className="mt-0.5 h-4 w-4 text-muted-foreground" aria-hidden />
        <div className="space-y-1 text-sm">
          <p className="font-medium">No policy matched</p>
          <p className="text-muted-foreground">
            This action was routed for review by the risk engine rather than a specific policy rule.
          </p>
        </div>
      </div>
    )
  }

  const conditions = humanizeConditions(policy.conditions)
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-primary" aria-hidden />
        <span className="font-medium">{policy.policy_name}</span>
        {policy.decision ? <Badge variant="outline">{policy.decision.replace(/_/g, ' ')}</Badge> : null}
      </div>

      <div>
        <p className="text-xs font-medium uppercase text-muted-foreground">Matched Conditions</p>
        {conditions.length > 0 ? (
          <ul className="mt-1 space-y-1 text-sm">
            {conditions.map((c, i) => (
              <li key={i}>• {c}</li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-sm text-muted-foreground">Applies to all matching actions.</p>
        )}
      </div>

      {policy.reason ? (
        <div>
          <p className="text-xs font-medium uppercase text-muted-foreground">Decision</p>
          <p className="mt-1 text-sm">{policy.reason}</p>
        </div>
      ) : null}
    </div>
  )
}
