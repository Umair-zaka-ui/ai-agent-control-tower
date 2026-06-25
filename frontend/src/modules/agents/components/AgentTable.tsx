import { Link } from 'react-router-dom'
import {
  Archive,
  ChevronDown,
  ChevronUp,
  MoreHorizontal,
  Pencil,
  PauseCircle,
  PlayCircle,
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
import { cn } from '@/utils/cn'
import type { Agent, AgentSortField, AgentStatus } from '../types'
import { AgentHealthBadge } from './AgentHealthBadge'
import { AgentStatusBadge } from './AgentStatusBadge'
import { RiskLevelBadge } from './RiskLevelBadge'

interface SortableColumn {
  key: AgentSortField
  label: string
}

const SORTABLE_COLUMNS: SortableColumn[] = [
  { key: 'name', label: 'Name' },
  { key: 'agent_type', label: 'Type' },
  { key: 'status', label: 'Status' },
  { key: 'risk_level', label: 'Risk' },
  { key: 'version', label: 'Version' },
]

interface AgentTableProps {
  agents: Agent[]
  sortBy: AgentSortField
  sortDir: 'asc' | 'desc'
  onSort: (field: AgentSortField) => void
  onStatusChange: (agent: Agent, status: AgentStatus) => void
  onDelete: (agent: Agent) => void
}

export function AgentTable({
  agents,
  sortBy,
  sortDir,
  onSort,
  onStatusChange,
  onDelete,
}: AgentTableProps) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          {SORTABLE_COLUMNS.map((col) => (
            <TableHead key={col.key}>
              <button
                type="button"
                onClick={() => onSort(col.key)}
                className="inline-flex items-center gap-1 font-medium hover:text-foreground"
                aria-label={`Sort by ${col.label}`}
              >
                {col.label}
                {sortBy === col.key ? (
                  sortDir === 'asc' ? (
                    <ChevronUp className="h-3 w-3" />
                  ) : (
                    <ChevronDown className="h-3 w-3" />
                  )
                ) : null}
              </button>
            </TableHead>
          ))}
          <TableHead>Owner</TableHead>
          <TableHead>Health</TableHead>
          <TableHead>Last Activity</TableHead>
          <TableHead>Created</TableHead>
          <TableHead className="text-right">Actions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {agents.map((agent) => (
          <TableRow key={agent.id}>
            <TableCell className="font-medium">
              <Link
                to={`${ROUTES.AGENTS}/${agent.id}`}
                className="hover:text-primary hover:underline"
              >
                {agent.name}
              </Link>
            </TableCell>
            <TableCell className="capitalize text-muted-foreground">{agent.agent_type}</TableCell>
            <TableCell>
              <AgentStatusBadge status={agent.status} />
            </TableCell>
            <TableCell>
              <RiskLevelBadge level={agent.risk_level} />
            </TableCell>
            <TableCell className="text-muted-foreground">{agent.version}</TableCell>
            <TableCell className="text-muted-foreground">{agent.owner ?? '—'}</TableCell>
            <TableCell>
              <AgentHealthBadge health={agent.health} />
            </TableCell>
            <TableCell className="whitespace-nowrap text-muted-foreground">
              {formatRelativeTime(agent.updated_at)}
            </TableCell>
            <TableCell className="whitespace-nowrap text-muted-foreground">
              {formatDate(agent.created_at)}
            </TableCell>
            <TableCell className="text-right">
              <AgentRowActions
                agent={agent}
                onStatusChange={onStatusChange}
                onDelete={onDelete}
              />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function AgentRowActions({
  agent,
  onStatusChange,
  onDelete,
}: {
  agent: Agent
  onStatusChange: (agent: Agent, status: AgentStatus) => void
  onDelete: (agent: Agent) => void
}) {
  const isActive = agent.status === 'ACTIVE'
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Actions for ${agent.name}`}>
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem asChild>
          <Link to={`${ROUTES.AGENTS}/${agent.id}`}>View</Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link to={`${ROUTES.AGENTS}/${agent.id}/edit`}>
            <Pencil />
            Edit
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {isActive ? (
          <DropdownMenuItem onClick={() => onStatusChange(agent, 'SUSPENDED')}>
            <PauseCircle />
            Suspend
          </DropdownMenuItem>
        ) : (
          <DropdownMenuItem onClick={() => onStatusChange(agent, 'ACTIVE')}>
            <PlayCircle />
            Activate
          </DropdownMenuItem>
        )}
        {agent.status !== 'ARCHIVED' ? (
          <DropdownMenuItem onClick={() => onStatusChange(agent, 'ARCHIVED')}>
            <Archive />
            Archive
          </DropdownMenuItem>
        ) : null}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          className={cn('text-destructive focus:text-destructive')}
          onClick={() => onDelete(agent)}
        >
          <Trash2 />
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
