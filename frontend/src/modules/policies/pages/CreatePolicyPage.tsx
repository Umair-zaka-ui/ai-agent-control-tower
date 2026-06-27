import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'

import { PageHeader } from '@/components/common/PageHeader'
import { ROUTES } from '@/constants/routes'
import { useAuth } from '@/hooks/useAuth'
import { useNotifications } from '@/hooks/useNotifications'
import { apiErrorMessage } from '@/utils/error'
import { PolicyBuilder, type PolicyBuilderInitial } from '../components'
import { useCreatePolicy } from '../hooks'
import type { PolicyCreateInput } from '../types'
import { canManagePolicies } from '../utils/permissions'
import { ForbiddenNotice } from './ForbiddenNotice'

export function CreatePolicyPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const notify = useNotifications()
  const { user } = useAuth()
  const createPolicy = useCreatePolicy()

  if (!canManagePolicies(user?.role)) return <ForbiddenNotice />

  // A template may pre-seed the builder via router state (Templates → Use).
  const initial = (location.state as { initial?: Partial<PolicyBuilderInitial> } | null)?.initial

  const handleSubmit = (input: PolicyCreateInput) => {
    createPolicy.mutate(input, {
      onSuccess: (policy) => {
        notify.success(`Created ${policy.name}`)
        navigate(`${ROUTES.POLICIES}/${policy.id}`)
      },
      onError: (e) => notify.error('Could not create policy', apiErrorMessage(e)),
    })
  }

  return (
    <div className="space-y-6">
      <Link
        to={ROUTES.POLICIES}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        All policies
      </Link>

      <PageHeader title="Create Policy" description="Define a governance rule in six guided steps." />

      <PolicyBuilder
        mode="create"
        initial={initial}
        busy={createPolicy.isPending}
        onSubmit={handleSubmit}
        onCancel={() => navigate(ROUTES.POLICIES)}
      />
    </div>
  )
}
