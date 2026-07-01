import { useMemo, useState } from 'react'
import { AlertCircle, ArrowLeft, ChevronLeft, ChevronRight, RefreshCw, ScrollText } from 'lucide-react'
import { Link } from 'react-router-dom'

import { EmptyState } from '@/components/common/EmptyState'
import { PageHeader } from '@/components/common/PageHeader'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import {
  AuditFilters,
  type AuditFilterValues,
  AuditSearch,
  AuditTable,
  AuditTableSkeleton,
} from '../components'
import { useAudit, useAuditEventTypes } from '../hooks'
import { AUDIT_PAGE_SIZE, SEARCH_DEBOUNCE_MS } from '../utils/constants'
import { humanizeToken } from '../utils/format'

export function AuditEventsPage() {
  const [search, setSearch] = useState('')
  const debouncedSearch = useDebouncedValue(search, SEARCH_DEBOUNCE_MS)
  const [filters, setFilters] = useState<AuditFilterValues>({})
  const [page, setPage] = useState(0)

  const { data: catalog } = useAuditEventTypes()
  const eventTypeOptions = useMemo(
    () => (catalog ?? []).map((c) => ({ value: c.value, label: c.label })),
    [catalog],
  )

  const params = useMemo(
    () => ({
      search: debouncedSearch.trim() || undefined,
      ...filters,
      limit: AUDIT_PAGE_SIZE,
      offset: page * AUDIT_PAGE_SIZE,
    }),
    [debouncedSearch, filters, page],
  )

  const { data, isLoading, isError, isFetching, refetch } = useAudit(params)
  const events = data ?? []
  const hasFilters = Boolean(
    debouncedSearch ||
      filters.event_type ||
      filters.category ||
      filters.actor_type ||
      filters.severity ||
      filters.decision ||
      filters.date_from ||
      filters.date_to,
  )

  // The list endpoint returns at most a full page; a full page implies more.
  const canPrev = page > 0
  const canNext = events.length === AUDIT_PAGE_SIZE

  const updateFilters = (next: AuditFilterValues) => {
    setFilters(next)
    setPage(0)
  }

  return (
    <div className="space-y-6">
      <div>
        <Link
          to={ROUTES.AUDIT}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          Audit overview
        </Link>
      </div>

      <PageHeader
        title="Audit Events"
        description="Search and filter every recorded event across agents, policies, approvals and access."
      />

      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <AuditSearch
          value={search}
          onChange={(v) => {
            setSearch(v)
            setPage(0)
          }}
        />
        <AuditFilters value={filters} onChange={updateFilters} eventTypeOptions={eventTypeOptions} />
      </div>

      {(() => {
        const labelParts = [
          filters.event_type && humanizeToken(filters.event_type),
          filters.severity && `${humanizeToken(filters.severity)} severity`,
        ].filter(Boolean)
        return labelParts.length ? (
          <p className="text-xs text-muted-foreground">Showing {labelParts.join(' · ')}</p>
        ) : null
      })()}

      <Card className="overflow-hidden">
        {isLoading ? (
          <AuditTableSkeleton rows={10} />
        ) : isError ? (
          <div role="alert" className="flex flex-col items-center gap-3 py-16 text-center">
            <AlertCircle className="h-6 w-6 text-destructive" />
            <p className="text-sm text-muted-foreground">Unable to load audit information.</p>
            <Button variant="outline" size="sm" onClick={() => void refetch()}>
              <RefreshCw className="h-4 w-4" />
              Retry
            </Button>
          </div>
        ) : events.length === 0 && !hasFilters ? (
          <div className="py-10">
            <EmptyState
              icon={ScrollText}
              title="No audit events available"
              description="Once users and AI agents begin operating, audit events will appear here."
            />
          </div>
        ) : events.length === 0 ? (
          <p className="py-16 text-center text-sm text-muted-foreground">
            No events match your search or filters.
          </p>
        ) : (
          <AuditTable events={events} />
        )}
      </Card>

      {!isError && (events.length > 0 || page > 0) && (
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            Page {page + 1}
            {isFetching ? ' · refreshing…' : ''}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={!canPrev || isFetching}
            >
              <ChevronLeft className="h-4 w-4" />
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => p + 1)}
              disabled={!canNext || isFetching}
            >
              Next
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
