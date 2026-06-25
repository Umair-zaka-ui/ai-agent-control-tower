import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertCircle, Bot, Plus, RefreshCw } from 'lucide-react'

import { EmptyState } from '@/components/common/EmptyState'
import { PageHeader } from '@/components/common/PageHeader'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'
import { useNotifications } from '@/hooks/useNotifications'
import { apiErrorMessage } from '@/utils/error'
import {
  AgentFilters,
  type AgentFilterValues,
  AgentPagination,
  AgentSearch,
  AgentTable,
  AgentTableSkeleton,
  AgentToolbar,
} from '../components'
import { useAgents, useDeleteAgent, useUpdateAgentStatus } from '../hooks'
import type { Agent, AgentSortField, AgentStatus } from '../types'
import { useDebouncedValue } from '../utils/useDebouncedValue'

export function AgentsListPage() {
  const navigate = useNavigate()
  const notify = useNotifications()

  const [search, setSearch] = useState('')
  const debouncedSearch = useDebouncedValue(search, 300)
  const [filters, setFilters] = useState<AgentFilterValues>({})
  const [sortBy, setSortBy] = useState<AgentSortField>('created_at')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)

  // Any change to search/filters/page-size resets back to the first page.
  useEffect(() => {
    setPage(1)
  }, [debouncedSearch, filters, pageSize])

  const params = useMemo(
    () => ({
      search: debouncedSearch.trim() || undefined,
      ...filters,
      sort_by: sortBy,
      sort_dir: sortDir,
      page,
      page_size: pageSize,
    }),
    [debouncedSearch, filters, sortBy, sortDir, page, pageSize],
  )

  const { data, isLoading, isError, isFetching, refetch } = useAgents(params)
  const updateStatus = useUpdateAgentStatus()
  const deleteAgent = useDeleteAgent()

  const agents = data?.items ?? []
  const total = data?.total ?? 0
  const hasFiltersApplied = Boolean(debouncedSearch || filters.status || filters.agent_type || filters.risk_level)

  const handleSort = (field: AgentSortField) => {
    if (field === sortBy) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortBy(field)
      setSortDir('asc')
    }
  }

  const handleStatusChange = (agent: Agent, status: AgentStatus) => {
    updateStatus.mutate(
      { id: agent.id, status },
      {
        onSuccess: () => notify.success(`${agent.name} → ${status.toLowerCase()}`),
        onError: (e) => notify.error('Could not update status', apiErrorMessage(e)),
      },
    )
  }

  const handleDelete = (agent: Agent) => {
    if (!window.confirm(`Delete agent "${agent.name}"? This cannot be undone.`)) return
    deleteAgent.mutate(agent.id, {
      onSuccess: () => notify.success(`Deleted ${agent.name}`),
      onError: (e) => notify.error('Could not delete agent', apiErrorMessage(e)),
    })
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Agents"
        description="Register, monitor, and manage your AI agents."
        actions={
          <AgentToolbar agents={agents} refreshing={isFetching} onRefresh={() => void refetch()} />
        }
      />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <AgentSearch value={search} onChange={setSearch} />
        <AgentFilters value={filters} onChange={setFilters} />
      </div>

      <Card className="overflow-hidden">
        {isLoading ? (
          <AgentTableSkeleton rows={pageSize > 10 ? 8 : pageSize} />
        ) : isError ? (
          <div role="alert" className="flex flex-col items-center gap-3 py-16 text-center">
            <AlertCircle className="h-6 w-6 text-destructive" />
            <p className="text-sm text-muted-foreground">Unable to load agents.</p>
            <Button variant="outline" size="sm" onClick={() => void refetch()}>
              <RefreshCw className="h-4 w-4" />
              Retry
            </Button>
          </div>
        ) : total === 0 && !hasFiltersApplied ? (
          <div className="py-10">
            <EmptyState
              icon={Bot}
              title="No agents registered"
              description="Create your first AI agent to start governing its actions."
              action={
                <Button onClick={() => navigate(`${ROUTES.AGENTS}/new`)}>
                  <Plus className="h-4 w-4" />
                  Create Agent
                </Button>
              }
            />
          </div>
        ) : agents.length === 0 ? (
          <p className="py-16 text-center text-sm text-muted-foreground">
            No agents match your search or filters.
          </p>
        ) : (
          <>
            <AgentTable
              agents={agents}
              sortBy={sortBy}
              sortDir={sortDir}
              onSort={handleSort}
              onStatusChange={handleStatusChange}
              onDelete={handleDelete}
            />
            <AgentPagination
              page={page}
              pageSize={pageSize}
              total={total}
              onPageChange={setPage}
              onPageSizeChange={setPageSize}
            />
          </>
        )}
      </Card>
    </div>
  )
}
