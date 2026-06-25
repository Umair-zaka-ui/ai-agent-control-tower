import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useRecentActions } from '@/hooks/useRecentActions'
import { formatRelativeTime } from '@/utils/format'
import { getRiskColorClass } from '@/utils/risk'
import { cn } from '@/utils/cn'
import { DecisionBadge } from './DecisionBadge'
import { WidgetCard } from './WidgetCard'

/** Short id for display when no friendly name is available. */
function shortId(id: string): string {
  return id.slice(0, 8)
}

/** Most recent agent actions with decision + risk (live: /dashboard/recent-actions). */
export function RecentAgentActions() {
  const { data, isLoading, isError, refetch } = useRecentActions(8)
  const isEmpty = Boolean(data && data.length === 0)

  return (
    <WidgetCard
      title="Recent Agent Actions"
      loading={isLoading}
      error={isError}
      isEmpty={isEmpty}
      emptyMessage="No agent actions recorded yet."
      onRetry={() => void refetch()}
      contentClassName="px-0"
    >
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Time</TableHead>
            <TableHead>Agent</TableHead>
            <TableHead>Resource</TableHead>
            <TableHead>Action</TableHead>
            <TableHead>Decision</TableHead>
            <TableHead className="text-right">Risk</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {(data ?? []).map((action) => (
            <TableRow key={action.id}>
              <TableCell className="whitespace-nowrap text-muted-foreground">
                {formatRelativeTime(action.created_at)}
              </TableCell>
              <TableCell className="font-mono text-xs">{shortId(action.agent_id)}</TableCell>
              <TableCell>{action.resource}</TableCell>
              <TableCell>{action.action}</TableCell>
              <TableCell>
                <DecisionBadge decision={action.decision} />
              </TableCell>
              <TableCell className={cn('text-right font-medium', getRiskColorClass(action.risk_score))}>
                {action.risk_score}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </WidgetCard>
  )
}
