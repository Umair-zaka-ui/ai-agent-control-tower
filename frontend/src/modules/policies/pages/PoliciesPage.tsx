import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertCircle, RefreshCw, ShieldCheck } from 'lucide-react'

import { EmptyState } from '@/components/common/EmptyState'
import { PageHeader } from '@/components/common/PageHeader'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useNotifications } from '@/hooks/useNotifications'
import { apiErrorMessage } from '@/utils/error'
import {
  DeleteConfirmModal,
  PolicyFilters,
  type PolicyFilterValues,
  PolicySearch,
  PolicyTable,
  PolicyTableSkeleton,
  PolicyToolbar,
} from '../components'
import { useCreatePolicy, useDeletePolicy, usePolicies, useTogglePolicy } from '../hooks'
import type { Policy } from '../types'
import { canManagePolicies, canTestPolicies } from '../utils/permissions'

export function PoliciesPage() {
  const navigate = useNavigate()
  const notify = useNotifications()
  const { user } = useAuth()
  const canManage = canManagePolicies(user?.role)
  const canTest = canTestPolicies(user?.role)

  const [search, setSearch] = useState('')
  const debouncedSearch = useDebouncedValue(search, 300)
  const [filters, setFilters] = useState<PolicyFilterValues>({})
  const [deleteTarget, setDeleteTarget] = useState<Policy | null>(null)

  const params = useMemo(
    () => ({ search: debouncedSearch.trim() || undefined, ...filters }),
    [debouncedSearch, filters],
  )

  const { data, isLoading, isError, isFetching, refetch } = usePolicies(params)
  const togglePolicy = useTogglePolicy()
  const createPolicy = useCreatePolicy()
  const deletePolicy = useDeletePolicy()

  const policies = data ?? []
  const hasFiltersApplied = Boolean(
    debouncedSearch || filters.status || filters.decision || filters.severity || filters.resource,
  )

  // Close the delete modal once the deletion settles.
  useEffect(() => {
    if (!deletePolicy.isPending && deleteTarget && deletePolicy.isSuccess) setDeleteTarget(null)
  }, [deletePolicy.isPending, deletePolicy.isSuccess, deleteTarget])

  const handleToggle = (policy: Policy) => {
    const enable = policy.status !== 'ENABLED'
    togglePolicy.mutate(
      { id: policy.id, enable },
      {
        onSuccess: () => notify.success(`${policy.name} ${enable ? 'enabled' : 'disabled'}`),
        onError: (e) => notify.error('Could not update policy', apiErrorMessage(e)),
      },
    )
  }

  const handleDuplicate = (policy: Policy) => {
    createPolicy.mutate(
      {
        name: `${policy.name} (copy)`,
        description: policy.description,
        resource: policy.resource,
        action: policy.action,
        conditions: policy.conditions,
        decision: policy.decision,
        priority: policy.priority,
        severity: policy.severity,
        status: 'DRAFT',
      },
      {
        onSuccess: () => notify.success(`Duplicated ${policy.name}`),
        onError: (e) => notify.error('Could not duplicate policy', apiErrorMessage(e)),
      },
    )
  }

  const handleConfirmDelete = () => {
    if (!deleteTarget) return
    deletePolicy.mutate(deleteTarget.id, {
      onSuccess: () => notify.success(`Deleted ${deleteTarget.name}`),
      onError: (e) => notify.error('Could not delete policy', apiErrorMessage(e)),
    })
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Policies"
        description="Author and manage database-driven governance policies."
        actions={
          <PolicyToolbar
            policies={policies}
            refreshing={isFetching}
            canManage={canManage}
            onRefresh={() => void refetch()}
          />
        }
      />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <PolicySearch value={search} onChange={setSearch} />
        <PolicyFilters value={filters} onChange={setFilters} />
      </div>

      <Card className="overflow-hidden">
        {isLoading ? (
          <PolicyTableSkeleton rows={8} />
        ) : isError ? (
          <div role="alert" className="flex flex-col items-center gap-3 py-16 text-center">
            <AlertCircle className="h-6 w-6 text-destructive" />
            <p className="text-sm text-muted-foreground">Unable to load policies.</p>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => void refetch()}>
                <RefreshCw className="h-4 w-4" />
                Retry
              </Button>
              <Button variant="ghost" size="sm" onClick={() => navigate(ROUTES.DASHBOARD)}>
                Go back
              </Button>
            </div>
          </div>
        ) : policies.length === 0 && !hasFiltersApplied ? (
          <div className="py-10">
            <EmptyState
              icon={ShieldCheck}
              title="No policies configured"
              description="Create your first governance policy to control AI agent behavior."
              action={
                <div className="flex gap-2">
                  {canManage && (
                    <Button onClick={() => navigate(`${ROUTES.POLICIES}/new`)}>Create Policy</Button>
                  )}
                  <Button variant="outline" onClick={() => navigate(`${ROUTES.POLICIES}/templates`)}>
                    Use Template
                  </Button>
                </div>
              }
            />
          </div>
        ) : policies.length === 0 ? (
          <p className="py-16 text-center text-sm text-muted-foreground">
            No policies match your search or filters.
          </p>
        ) : (
          <PolicyTable
            policies={policies}
            canManage={canManage}
            canTest={canTest}
            onToggle={handleToggle}
            onDuplicate={handleDuplicate}
            onDelete={setDeleteTarget}
          />
        )}
      </Card>

      <DeleteConfirmModal
        open={deleteTarget !== null}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        policyName={deleteTarget?.name ?? ''}
        loading={deletePolicy.isPending}
        onConfirm={handleConfirmDelete}
      />
    </div>
  )
}
