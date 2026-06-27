import { Link } from 'react-router-dom'
import {
  Copy,
  FlaskConical,
  MoreHorizontal,
  Pencil,
  Power,
  PowerOff,
  Trash2,
} from 'lucide-react'

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
import { formatDate, formatRelativeTime } from '@/utils/format'
import type { Policy } from '../types'
import { PolicyDecisionBadge } from './PolicyDecisionBadge'
import { PolicySeverityBadge } from './PolicySeverityBadge'
import { PolicyStatusBadge } from './PolicyStatusBadge'

interface PolicyTableProps {
  policies: Policy[]
  canManage: boolean
  canTest: boolean
  onToggle: (policy: Policy) => void
  onDuplicate: (policy: Policy) => void
  onDelete: (policy: Policy) => void
}

export function PolicyTable({
  policies,
  canManage,
  canTest,
  onToggle,
  onDuplicate,
  onDelete,
}: PolicyTableProps) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Policy</TableHead>
          <TableHead>Resource</TableHead>
          <TableHead>Action</TableHead>
          <TableHead>Decision</TableHead>
          <TableHead>Severity</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Triggers</TableHead>
          <TableHead>Last Triggered</TableHead>
          <TableHead>Created</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {policies.map((policy) => (
          <TableRow key={policy.id}>
            <TableCell className="font-medium">
              <Link to={`${ROUTES.POLICIES}/${policy.id}`} className="hover:text-primary hover:underline">
                {policy.name}
              </Link>
            </TableCell>
            <TableCell className="text-muted-foreground">{policy.resource}</TableCell>
            <TableCell className="text-muted-foreground">{policy.action.replace(/_/g, ' ')}</TableCell>
            <TableCell>
              <PolicyDecisionBadge decision={policy.decision} />
            </TableCell>
            <TableCell>
              <PolicySeverityBadge severity={policy.severity} />
            </TableCell>
            <TableCell>
              <PolicyStatusBadge status={policy.status} />
            </TableCell>
            <TableCell className="text-right tabular-nums">{policy.trigger_count}</TableCell>
            <TableCell className="whitespace-nowrap text-muted-foreground">
              {policy.last_triggered_at ? formatRelativeTime(policy.last_triggered_at) : '—'}
            </TableCell>
            <TableCell className="whitespace-nowrap text-muted-foreground">
              {formatDate(policy.created_at)}
            </TableCell>
            <TableCell className="text-right">
              <PolicyRowActions
                policy={policy}
                canManage={canManage}
                canTest={canTest}
                onToggle={onToggle}
                onDuplicate={onDuplicate}
                onDelete={onDelete}
              />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function PolicyRowActions({
  policy,
  canManage,
  canTest,
  onToggle,
  onDuplicate,
  onDelete,
}: {
  policy: Policy
  canManage: boolean
  canTest: boolean
  onToggle: (policy: Policy) => void
  onDuplicate: (policy: Policy) => void
  onDelete: (policy: Policy) => void
}) {
  const enabled = policy.status === 'ENABLED'
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Actions for ${policy.name}`}>
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem asChild>
          <Link to={`${ROUTES.POLICIES}/${policy.id}`}>View</Link>
        </DropdownMenuItem>
        {canTest && (
          <DropdownMenuItem asChild>
            <Link to={`${ROUTES.POLICIES}/${policy.id}/test`}>
              <FlaskConical />
              Test
            </Link>
          </DropdownMenuItem>
        )}
        {canManage && (
          <>
            <DropdownMenuItem asChild>
              <Link to={`${ROUTES.POLICIES}/${policy.id}/edit`}>
                <Pencil />
                Edit
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => onDuplicate(policy)}>
              <Copy />
              Duplicate
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => onToggle(policy)}>
              {enabled ? <PowerOff /> : <Power />}
              {enabled ? 'Disable' : 'Enable'}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive focus:text-destructive"
              onClick={() => onDelete(policy)}
            >
              <Trash2 />
              Delete
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
