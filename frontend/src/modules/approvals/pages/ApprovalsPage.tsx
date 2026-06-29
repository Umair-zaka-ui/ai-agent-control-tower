import { useMemo, useState } from 'react'
import { AlertCircle, CheckCircle2, CheckSquare, RefreshCw } from 'lucide-react'

import { EmptyState } from '@/components/common/EmptyState'
import { PageHeader } from '@/components/common/PageHeader'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useAuth } from '@/hooks/useAuth'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useNotifications } from '@/hooks/useNotifications'
import type { ID } from '@/types'
import { apiErrorMessage } from '@/utils/error'
import {
  ApprovalFilters,
  type ApprovalFilterValues,
  ApprovalSearch,
  ApprovalStatsCards,
  ApprovalTable,
  ApprovalTableSkeleton,
  ApprovalToolbar,
  RejectDialog,
  ReviewDialog,
} from '../components'
import { useApprovals, useApprovalStatistics, useApprove, useReject } from '../hooks'
import type { ApprovalListItem } from '../types'
import { RISK_RANGES } from '../utils/constants'
import { canReviewApprovals } from '../utils/permissions'

export function ApprovalsPage() {
  const notify = useNotifications()
  const { permissions } = useAuth()
  const canReview = canReviewApprovals(permissions)

  const [search, setSearch] = useState('')
  const debouncedSearch = useDebouncedValue(search, 300)
  const [filters, setFilters] = useState<ApprovalFilterValues>({ status: 'PENDING' })
  const [selected, setSelected] = useState<Set<ID>>(new Set())
  const [approveTarget, setApproveTarget] = useState<ApprovalListItem | null>(null)
  const [rejectTarget, setRejectTarget] = useState<ApprovalListItem | null>(null)

  const params = useMemo(() => {
    const range = RISK_RANGES.find((r) => r.value === filters.risk)
    return {
      search: debouncedSearch.trim() || undefined,
      status: filters.status,
      priority: filters.priority,
      risk_min: range?.min,
      risk_max: range?.max,
    }
  }, [debouncedSearch, filters])

  const { data, isLoading, isError, isFetching, refetch } = useApprovals(params)
  const { data: stats, isLoading: statsLoading } = useApprovalStatistics()
  const approve = useApprove()
  const reject = useReject()

  const approvals = data ?? []
  const hasFilters = Boolean(
    debouncedSearch || filters.priority || filters.risk || filters.status !== 'PENDING',
  )

  const toggleSelect = (id: ID) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const toggleSelectAll = () =>
    setSelected((prev) =>
      prev.size === approvals.length ? new Set() : new Set(approvals.map((a) => a.id)),
    )

  const handleApprove = (comment: string) => {
    if (!approveTarget) return
    approve.mutate(
      { id: approveTarget.id, input: { review_comment: comment } },
      {
        onSuccess: () => {
          notify.success('Approval approved')
          setApproveTarget(null)
          setSelected(new Set())
        },
        onError: (e) => notify.error('Could not approve', apiErrorMessage(e)),
      },
    )
  }

  const handleReject = (reason: string) => {
    if (!rejectTarget) return
    reject.mutate(
      { id: rejectTarget.id, input: { review_comment: reason } },
      {
        onSuccess: () => {
          notify.success('Approval rejected')
          setRejectTarget(null)
          setSelected(new Set())
        },
        onError: (e) => notify.error('Could not reject', apiErrorMessage(e)),
      },
    )
  }

  const bulkApprove = () => {
    const ids = [...selected]
    Promise.allSettled(
      ids.map((id) => approve.mutateAsync({ id, input: { review_comment: 'Bulk approved' } })),
    ).then((results) => {
      const ok = results.filter((r) => r.status === 'fulfilled').length
      notify.success(`Approved ${ok} of ${ids.length}`)
      setSelected(new Set())
    })
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Approval Queue"
        description="Review, approve, reject and escalate AI agent decisions awaiting human sign-off."
        actions={
          <ApprovalToolbar approvals={approvals} refreshing={isFetching} onRefresh={() => void refetch()} />
        }
      />

      <ApprovalStatsCards stats={stats} loading={statsLoading} />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <ApprovalSearch value={search} onChange={setSearch} />
        <ApprovalFilters value={filters} onChange={setFilters} />
      </div>

      {canReview && selected.size > 0 && (
        <div className="flex items-center justify-between rounded-md border border-border bg-muted/40 px-4 py-2">
          <span className="text-sm font-medium">{selected.size} selected</span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={bulkApprove} disabled={approve.isPending}>
              <CheckCircle2 className="h-4 w-4" />
              Approve selected
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
              Clear
            </Button>
          </div>
        </div>
      )}

      <Card className="overflow-hidden">
        {isLoading ? (
          <ApprovalTableSkeleton rows={8} />
        ) : isError ? (
          <div role="alert" className="flex flex-col items-center gap-3 py-16 text-center">
            <AlertCircle className="h-6 w-6 text-destructive" />
            <p className="text-sm text-muted-foreground">Unable to load approvals.</p>
            <Button variant="outline" size="sm" onClick={() => void refetch()}>
              <RefreshCw className="h-4 w-4" />
              Retry
            </Button>
          </div>
        ) : approvals.length === 0 && !hasFilters ? (
          <div className="py-10">
            <EmptyState
              icon={CheckSquare}
              title="No approvals waiting"
              description="All AI actions have been reviewed."
            />
          </div>
        ) : approvals.length === 0 ? (
          <p className="py-16 text-center text-sm text-muted-foreground">
            No approvals match your search or filters.
          </p>
        ) : (
          <ApprovalTable
            approvals={approvals}
            canReview={canReview}
            selectable={canReview}
            selected={selected}
            onToggleSelect={toggleSelect}
            onToggleSelectAll={toggleSelectAll}
            onApprove={canReview ? setApproveTarget : undefined}
            onReject={canReview ? setRejectTarget : undefined}
          />
        )}
      </Card>

      <ReviewDialog
        open={approveTarget !== null}
        onOpenChange={(o) => !o && setApproveTarget(null)}
        loading={approve.isPending}
        onConfirm={handleApprove}
      />
      <RejectDialog
        open={rejectTarget !== null}
        onOpenChange={(o) => !o && setRejectTarget(null)}
        loading={reject.isPending}
        onConfirm={handleReject}
      />
    </div>
  )
}
