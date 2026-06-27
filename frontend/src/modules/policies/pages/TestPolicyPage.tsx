import { Link, useParams } from 'react-router-dom'
import { AlertCircle, ArrowLeft } from 'lucide-react'

import { PageHeader } from '@/components/common/PageHeader'
import { FullPageSpinner } from '@/components/common/Spinner'
import { Button } from '@/components/ui/button'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'
import { useNotifications } from '@/hooks/useNotifications'
import { apiErrorMessage } from '@/utils/error'
import { PolicyTestPanel } from '../components'
import { usePolicy, useTestPolicy } from '../hooks'
import type { PolicyTestRequest } from '../types'
import { canTestPolicies } from '../utils/permissions'
import { ForbiddenNotice } from './ForbiddenNotice'

export function TestPolicyPage() {
  const { id } = useParams<{ id: string }>()
  const notify = useNotifications()
  const { user } = useAuth()
  const { data: policy, isLoading, isError } = usePolicy(id)
  const testPolicy = useTestPolicy()

  if (!canTestPolicies(user?.role)) return <ForbiddenNotice />
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

  const handleTest = (payload: PolicyTestRequest) => {
    testPolicy.mutate(
      { id: policy.id, payload },
      { onError: (e) => notify.error('Test failed', apiErrorMessage(e)) },
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

      <PageHeader
        title={`Test ${policy.name}`}
        description="Simulate an agent action and see whether this policy would trigger."
      />

      <PolicyTestPanel
        policy={policy}
        busy={testPolicy.isPending}
        result={testPolicy.data}
        onTest={handleTest}
      />
    </div>
  )
}
