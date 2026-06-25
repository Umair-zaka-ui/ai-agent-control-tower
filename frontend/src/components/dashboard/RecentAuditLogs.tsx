import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useRecentAuditLogs } from '@/hooks/useRecentAuditLogs'
import { formatRelativeTime } from '@/utils/format'
import type { AuditLog } from '@/types'
import { WidgetCard } from './WidgetCard'

/** Derive a display severity from the event type (no backend severity field). */
function severityFor(event: string): { label: string; variant: 'destructive' | 'warning' | 'secondary' } {
  const e = event.toLowerCase()
  if (/(block|delete|revoke|reject|suspend|fail)/.test(e)) return { label: 'High', variant: 'destructive' }
  if (/(approve|update|pending|create)/.test(e)) return { label: 'Medium', variant: 'warning' }
  return { label: 'Info', variant: 'secondary' }
}

function actorLabel(log: AuditLog): string {
  if (log.actor_id) return `${log.actor_type} ${log.actor_id.slice(0, 8)}`
  return log.actor_type
}

/** Most recent audit-trail entries (live: /audit-logs). */
export function RecentAuditLogs() {
  const { data, isLoading, isError, refetch } = useRecentAuditLogs(6)
  const isEmpty = Boolean(data && data.length === 0)

  return (
    <WidgetCard
      title="Recent Audit Logs"
      loading={isLoading}
      error={isError}
      isEmpty={isEmpty}
      emptyMessage="No audit events recorded yet."
      onRetry={() => void refetch()}
      contentClassName="px-0"
    >
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Time</TableHead>
            <TableHead>Actor</TableHead>
            <TableHead>Event</TableHead>
            <TableHead>Entity</TableHead>
            <TableHead className="text-right">Severity</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {(data ?? []).map((log) => {
            const severity = severityFor(log.event_type)
            return (
              <TableRow key={log.id}>
                <TableCell className="whitespace-nowrap text-muted-foreground">
                  {formatRelativeTime(log.created_at)}
                </TableCell>
                <TableCell className="font-mono text-xs">{actorLabel(log)}</TableCell>
                <TableCell>{log.event_type}</TableCell>
                <TableCell className="text-muted-foreground">{log.entity_type}</TableCell>
                <TableCell className="text-right">
                  <Badge variant={severity.variant}>{severity.label}</Badge>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </WidgetCard>
  )
}
