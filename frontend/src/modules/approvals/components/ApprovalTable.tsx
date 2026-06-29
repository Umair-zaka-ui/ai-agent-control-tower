import { Link } from 'react-router-dom'
import { CheckCircle2, Eye, MoreHorizontal, ShieldAlert, XCircle } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ROUTES } from '@/constants/routes'
import type { ID } from '@/types'
import { formatRelativeTime } from '@/utils/format'
import { cn } from '@/utils/cn'
import type { ApprovalListItem } from '../types'
import { humanizeToken } from '../utils/format'
import { ApprovalStatusBadge } from './ApprovalStatusBadge'
import { PriorityBadge } from './PriorityBadge'
import { RiskBadge } from './RiskBadge'

interface ApprovalTableProps {
  approvals: ApprovalListItem[]
  canReview: boolean
  selectable?: boolean
  selected?: Set<ID>
  onToggleSelect?: (id: ID) => void
  onToggleSelectAll?: () => void
  onApprove?: (approval: ApprovalListItem) => void
  onReject?: (approval: ApprovalListItem) => void
}

export function ApprovalTable({
  approvals,
  canReview,
  selectable = false,
  selected,
  onToggleSelect,
  onToggleSelectAll,
  onApprove,
  onReject,
}: ApprovalTableProps) {
  const allSelected = selectable && approvals.length > 0 && selected?.size === approvals.length

  return (
    <Table>
      <TableHeader>
        <TableRow>
          {selectable && (
            <TableHead className="w-10">
              <input
                type="checkbox"
                aria-label="Select all approvals"
                checked={allSelected}
                onChange={onToggleSelectAll}
                className="h-4 w-4 cursor-pointer rounded border-input accent-primary"
              />
            </TableHead>
          )}
          <TableHead>Approval ID</TableHead>
          <TableHead>Agent</TableHead>
          <TableHead>Action</TableHead>
          <TableHead>Resource</TableHead>
          <TableHead className="text-right">Risk</TableHead>
          <TableHead>Priority</TableHead>
          <TableHead>Created</TableHead>
          <TableHead>Reviewer</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {approvals.map((approval) => {
          const isSelected = selected?.has(approval.id) ?? false
          const reviewable = approval.decision === 'PENDING' || approval.decision === 'ESCALATED'
          return (
            <TableRow key={approval.id} className={cn(isSelected && 'bg-muted/40')}>
              {selectable && (
                <TableCell>
                  <input
                    type="checkbox"
                    aria-label={`Select approval ${approval.id}`}
                    checked={isSelected}
                    onChange={() => onToggleSelect?.(approval.id)}
                    className="h-4 w-4 cursor-pointer rounded border-input accent-primary"
                  />
                </TableCell>
              )}
              <TableCell className="font-mono text-xs">
                <Link
                  to={`${ROUTES.APPROVALS}/${approval.id}`}
                  className="hover:text-primary hover:underline"
                >
                  {String(approval.id).slice(0, 8)}
                </Link>
              </TableCell>
              <TableCell className="font-medium">{approval.agent_name ?? '—'}</TableCell>
              <TableCell className="text-muted-foreground">{humanizeToken(approval.action)}</TableCell>
              <TableCell className="text-muted-foreground">{approval.resource}</TableCell>
              <TableCell className="text-right">
                <RiskBadge score={approval.risk_score} />
              </TableCell>
              <TableCell>
                <PriorityBadge priority={approval.priority} />
              </TableCell>
              <TableCell className="whitespace-nowrap text-muted-foreground">
                {formatRelativeTime(approval.created_at)}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {approval.assigned_to_name ?? approval.reviewer_name ?? 'Unassigned'}
              </TableCell>
              <TableCell>
                <ApprovalStatusBadge status={approval.decision} />
              </TableCell>
              <TableCell className="text-right">
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon" aria-label={`Actions for ${approval.id}`}>
                      <MoreHorizontal className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem asChild>
                      <Link to={`${ROUTES.APPROVALS}/${approval.id}`}>
                        <Eye />
                        View details
                      </Link>
                    </DropdownMenuItem>
                    {canReview && reviewable && (
                      <DropdownMenuItem asChild>
                        <Link to={`${ROUTES.APPROVALS}/${approval.id}/review`}>
                          <ShieldAlert />
                          Open workbench
                        </Link>
                      </DropdownMenuItem>
                    )}
                    {canReview && reviewable && (onApprove || onReject) && (
                      <>
                        <DropdownMenuSeparator />
                        {onApprove && (
                          <DropdownMenuItem onClick={() => onApprove(approval)}>
                            <CheckCircle2 />
                            Approve
                          </DropdownMenuItem>
                        )}
                        {onReject && (
                          <DropdownMenuItem
                            className="text-destructive focus:text-destructive"
                            onClick={() => onReject(approval)}
                          >
                            <XCircle />
                            Reject
                          </DropdownMenuItem>
                        )}
                      </>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
              </TableCell>
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}
