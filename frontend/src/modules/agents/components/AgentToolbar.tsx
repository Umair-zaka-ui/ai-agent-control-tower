import { useNavigate } from 'react-router-dom'
import { Download, Plus, RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ROUTES } from '@/constants/routes'
import type { Agent } from '../types'
import { exportAgentsCsv, exportAgentsJson } from '../utils/export'

interface AgentToolbarProps {
  /** Rows currently loaded (exported as-is). */
  agents: Agent[]
  refreshing?: boolean
  onRefresh: () => void
}

/** Top action bar for the agents list: create, refresh, export. */
export function AgentToolbar({ agents, refreshing, onRefresh }: AgentToolbarProps) {
  const navigate = useNavigate()

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button onClick={() => navigate(`${ROUTES.AGENTS}/new`)}>
        <Plus className="h-4 w-4" />
        Create Agent
      </Button>

      <Button variant="outline" onClick={onRefresh} disabled={refreshing}>
        <RefreshCw className="h-4 w-4" />
        Refresh
      </Button>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" disabled={agents.length === 0}>
            <Download className="h-4 w-4" />
            Export
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={() => exportAgentsCsv(agents)}>Export CSV</DropdownMenuItem>
          <DropdownMenuItem onClick={() => exportAgentsJson(agents)}>Export JSON</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
