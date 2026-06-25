import { Check, X } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useApprovalActions, usePendingApprovals } from '@/hooks/useApprovals'
import { useNotifications } from '@/hooks/useNotifications'
import { formatRelativeTime } from '@/utils/format'
import type { ApprovalPriority } from '@/types'
import { WidgetCard } from './WidgetCard'

const PRIORITY_VARIANT: Record<ApprovalPriority, 'destructive' | 'warning' | 'secondary'> = {
  CRITICAL: 'destructive',
  HIGH: 'destructive',
  MEDIUM: 'warning',
  LOW: 'secondary',
}

/** Latest pending approvals with inline approve/reject (live + auto-refresh). */
export function PendingApprovalWidget() {
  const { data, isLoading, isError, refetch } = usePendingApprovals()
  const { approve, reject } = useApprovalActions()
  const notify = useNotifications()

  const rows = (data ?? []).slice(0, 5)
  const isEmpty = Boolean(data && data.length === 0)
  const busyId = approve.variables ?? reject.variables
  const pending = approve.isPending || reject.isPending

  const onApprove = (id: string) =>
    approve.mutate(id, {
      onSuccess: () => notify.success('Approval granted'),
      onError: () => notify.error('Could not approve'),
    })

  const onReject = (id: string) =>
    reject.mutate(id, {
      onSuccess: () => notify.info('Approval rejected'),
      onError: () => notify.error('Could not reject'),
    })

  return (
    <WidgetCard
      title="Pending Approvals"
      loading={isLoading}
      error={isError}
      isEmpty={isEmpty}
      emptyMessage="No approvals waiting — you're all caught up."
      onRetry={() => void refetch()}
      contentClassName="px-0"
    >
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Agent</TableHead>
            <TableHead>Priority</TableHead>
            <TableHead>Created</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((approval) => (
            <TableRow key={approval.id}>
              <TableCell className="font-mono text-xs">
                {approval.requested_by_agent_id.slice(0, 8)}
              </TableCell>
              <TableCell>
                <Badge variant={PRIORITY_VARIANT[approval.priority]}>{approval.priority}</Badge>
              </TableCell>
              <TableCell className="whitespace-nowrap text-muted-foreground">
                {formatRelativeTime(approval.created_at)}
              </TableCell>
              <TableCell>
                <div className="flex justify-end gap-2">
                  <Button
                    size="sm"
                    variant="success"
                    disabled={pending}
                    aria-label="Approve"
                    onClick={() => onApprove(approval.id)}
                  >
                    <Check className="h-4 w-4" />
                    {busyId === approval.id && approve.isPending ? 'Approving…' : 'Approve'}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={pending}
                    aria-label="Reject"
                    onClick={() => onReject(approval.id)}
                  >
                    <X className="h-4 w-4" />
                    Reject
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </WidgetCard>
  )
}
