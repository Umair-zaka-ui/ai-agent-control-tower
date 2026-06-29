import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { formatDateTime } from '@/utils/format'
import type { ApprovalDetail } from '../types'
import { slaCountdown } from '../utils/format'
import { ApprovalStatusBadge } from './ApprovalStatusBadge'
import { PriorityBadge } from './PriorityBadge'
import { RiskBadge } from './RiskBadge'

/** Top-of-page summary card (SRS §Summary Card). */
export function ApprovalSummary({ approval }: { approval: ApprovalDetail }) {
  const sla = slaCountdown(approval.sla_due_at)
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Summary</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Approval ID" value={<span className="font-mono text-xs">{approval.id}</span>} />
          <Field label="Status" value={<ApprovalStatusBadge status={approval.decision} />} />
          <Field label="Priority" value={<PriorityBadge priority={approval.priority} />} />
          <Field label="Risk Score" value={<RiskBadge score={approval.risk.score} showLabel />} />
          <Field label="Created" value={formatDateTime(approval.created_at)} />
          <Field
            label="Review Deadline"
            value={
              approval.sla_due_at ? (
                <span className={sla?.overdue ? 'text-destructive' : sla?.urgent ? 'text-warning' : undefined}>
                  {formatDateTime(approval.sla_due_at)}
                  {sla ? ` · ${sla.label}` : ''}
                </span>
              ) : (
                '—'
              )
            }
          />
        </dl>
      </CardContent>
    </Card>
  )
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium">{value}</dd>
    </div>
  )
}
