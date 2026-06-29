import { Link } from 'react-router-dom'
import { AlertCircle, ArrowLeft, Clock, RefreshCw, ShieldAlert } from 'lucide-react'

import { EmptyState } from '@/components/common/EmptyState'
import { PageHeader } from '@/components/common/PageHeader'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'
import { cn } from '@/utils/cn'
import { formatRelativeTime } from '@/utils/format'
import { PriorityBadge, RiskBadge } from '../components'
import { useApprovalEscalations } from '../hooks'
import type { ApprovalListItem } from '../types'
import { ESCALATION_TARGET_LABELS } from '../utils/constants'
import { humanizeToken, slaCountdown } from '../utils/format'

export function EscalationsPage() {
  const { data, isLoading, isError, isFetching, refetch } = useApprovalEscalations()
  const escalations = data ?? []

  return (
    <div className="space-y-6">
      <Link
        to={ROUTES.APPROVALS}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Approval queue
      </Link>

      <PageHeader
        title="Escalations"
        description="Approvals routed for higher-level review, with live SLA countdowns."
        actions={
          <Button variant="outline" size="sm" onClick={() => void refetch()} disabled={isFetching}>
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
        }
      />

      {isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i} className="h-32 animate-pulse" />
          ))}
        </div>
      ) : isError ? (
        <Card>
          <CardContent role="alert" className="flex flex-col items-center gap-3 py-16 text-center">
            <AlertCircle className="h-6 w-6 text-destructive" />
            <p className="text-sm text-muted-foreground">Unable to load escalations.</p>
            <Button variant="outline" size="sm" onClick={() => void refetch()}>
              <RefreshCw className="h-4 w-4" />
              Retry
            </Button>
          </CardContent>
        </Card>
      ) : escalations.length === 0 ? (
        <EmptyState
          icon={ShieldAlert}
          title="No active escalations"
          description="Escalated approvals awaiting a higher-level decision will appear here."
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {escalations.map((item) => (
            <EscalationCard key={item.id} item={item} />
          ))}
        </div>
      )}
    </div>
  )
}

function EscalationCard({ item }: { item: ApprovalListItem }) {
  const sla = slaCountdown(item.sla_due_at)
  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-2">
          <div>
            <Link
              to={`${ROUTES.APPROVALS}/${item.id}/review`}
              className="font-medium hover:text-primary hover:underline"
            >
              {humanizeToken(item.action)} · {item.resource}
            </Link>
            <p className="text-xs text-muted-foreground">{item.agent_name ?? 'Unknown agent'}</p>
          </div>
          <RiskBadge score={item.risk_score} />
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          <PriorityBadge priority={item.priority} />
          {item.escalation_target ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-purple-500/15 px-2.5 py-0.5 text-purple-600 dark:text-purple-400">
              <ShieldAlert className="h-3 w-3" />
              {ESCALATION_TARGET_LABELS[item.escalation_target] ?? item.escalation_target}
            </span>
          ) : null}
        </div>

        <div className="flex items-center justify-between border-t border-border pt-3 text-xs text-muted-foreground">
          <span>Reviewer: {item.assigned_to_name ?? 'Unassigned'}</span>
          <span
            className={cn(
              'inline-flex items-center gap-1',
              sla?.overdue ? 'font-medium text-destructive' : sla?.urgent ? 'text-warning' : '',
            )}
          >
            <Clock className="h-3 w-3" />
            {sla ? sla.label : `Escalated ${formatRelativeTime(item.created_at)}`}
          </span>
        </div>
      </CardContent>
    </Card>
  )
}
