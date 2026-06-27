import { Link, useNavigate, useParams } from 'react-router-dom'
import { AlertCircle, ArrowLeft } from 'lucide-react'

import { PageHeader } from '@/components/common/PageHeader'
import { FullPageSpinner } from '@/components/common/Spinner'
import { Button } from '@/components/ui/button'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'
import { useNotifications } from '@/hooks/useNotifications'
import { apiErrorMessage } from '@/utils/error'
import { PolicyBuilder } from '../components'
import { usePolicy, useUpdatePolicy } from '../hooks'
import type { PolicyCreateInput } from '../types'
import { canManagePolicies } from '../utils/permissions'
import { ForbiddenNotice } from './ForbiddenNotice'

export function EditPolicyPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const notify = useNotifications()
  const { user } = useAuth()
  const { data: policy, isLoading, isError } = usePolicy(id)
  const updatePolicy = useUpdatePolicy()

  if (!canManagePolicies(user?.role)) return <ForbiddenNotice />
  if (isLoading) return <FullPageSpinner />
  if (isError || !policy) {
    return (
      <div role="alert" className="flex flex-col items-center gap-3 py-24 text-center">
        <AlertCircle className="h-7 w-7 text-destructive" />
        <p className="text-sm text-muted-foreground">Policy not found.</p>
        <Button variant="outline" asChild>
          <Link to={ROUTES.POLICIES}>Back to policies</Link>
        </Button>
      </div>
    )
  }

  const handleSubmit = (input: PolicyCreateInput) => {
    updatePolicy.mutate(
      { id: policy.id, input },
      {
        onSuccess: () => {
          notify.success('Policy updated')
          navigate(`${ROUTES.POLICIES}/${policy.id}`)
        },
        onError: (e) => notify.error('Could not update policy', apiErrorMessage(e)),
      },
    )
  }

  return (
    <div className="space-y-6">
      <Link
        to={`${ROUTES.POLICIES}/${policy.id}`}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to policy
      </Link>

      <PageHeader title={`Edit ${policy.name}`} description="Update this governance policy." />

      <PolicyBuilder
        mode="edit"
        initial={{
          name: policy.name,
          description: policy.description ?? '',
          severity: policy.severity,
          status: policy.status,
          resource: policy.resource,
          action: policy.action,
          conditionsText: JSON.stringify(policy.conditions ?? {}, null, 2),
          decision: policy.decision,
        }}
        busy={updatePolicy.isPending}
        onSubmit={handleSubmit}
        onCancel={() => navigate(`${ROUTES.POLICIES}/${policy.id}`)}
      />
    </div>
  )
}
