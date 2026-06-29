import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertCircle, ArrowLeft, Download, History, RefreshCw } from 'lucide-react'

import { EmptyState } from '@/components/common/EmptyState'
import { PageHeader } from '@/components/common/PageHeader'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select } from '@/components/ui/select'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { ApprovalSearch, ApprovalTable, ApprovalTableSkeleton } from '../components'
import { useApprovalHistory } from '../hooks'
import { APPROVAL_STATUSES } from '../utils/constants'
import { exportApprovalsCsv } from '../utils/export'
import { canReviewApprovals } from '../utils/permissions'

export function ApprovalHistoryPage() {
  const { permissions } = useAuth()
  const canReview = canReviewApprovals(permissions)

  const [search, setSearch] = useState('')
  const debouncedSearch = useDebouncedValue(search, 300)
  const [status, setStatus] = useState('')

  const params = useMemo(
    () => ({ search: debouncedSearch.trim() || undefined, status: status || undefined }),
    [debouncedSearch, status],
  )

  const { data, isLoading, isError, isFetching, refetch } = useApprovalHistory(params)
  const approvals = data ?? []

  return (
    <div className="space-y-6">
      <Link
        to={ROUTES.APPROVALS}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Approval queue
      </Link>

      <PageHeader
        title="Approval History"
        description="A complete record of every resolved AI agent decision."
        actions={
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => exportApprovalsCsv(approvals, 'approval-history.csv')}
              disabled={approvals.length === 0}
            >
              <Download className="h-4 w-4" />
              Export CSV
            </Button>
            <Button variant="outline" size="sm" onClick={() => void refetch()} disabled={isFetching}>
              <RefreshCw className="h-4 w-4" />
              Refresh
            </Button>
          </div>
        }
      />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <ApprovalSearch value={search} onChange={setSearch} />
        <Select
          aria-label="Filter by status"
          className="w-40"
          placeholder="All resolved"
          value={status}
          options={APPROVAL_STATUSES.filter((s) => s.value !== 'PENDING')}
          onChange={(e) => setStatus(e.target.value)}
        />
      </div>

      <Card className="overflow-hidden">
        {isLoading ? (
          <ApprovalTableSkeleton rows={8} />
        ) : isError ? (
          <div role="alert" className="flex flex-col items-center gap-3 py-16 text-center">
            <AlertCircle className="h-6 w-6 text-destructive" />
            <p className="text-sm text-muted-foreground">Unable to load history.</p>
            <Button variant="outline" size="sm" onClick={() => void refetch()}>
              <RefreshCw className="h-4 w-4" />
              Retry
            </Button>
          </div>
        ) : approvals.length === 0 ? (
          <div className="py-10">
            <EmptyState
              icon={History}
              title="No resolved approvals yet"
              description="Approved, rejected and escalated decisions will appear here."
            />
          </div>
        ) : (
          <ApprovalTable approvals={approvals} canReview={canReview} />
        )}
      </Card>
    </div>
  )
}
