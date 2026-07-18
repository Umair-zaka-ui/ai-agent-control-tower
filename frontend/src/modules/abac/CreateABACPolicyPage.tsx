import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { FilePlus2 } from 'lucide-react'

import { PageHeader } from '@/components/common'
import { ROUTES } from '@/constants/routes'
import { abacService } from '@/services'
import type { ABACPolicy, ABACPolicyWrite, ApiError } from '@/types'
import { PolicyBuilder } from './components/PolicyBuilder'

/** Create a draft ABAC policy with the visual builder (§33, §34). */
export function CreateABACPolicyPage() {
  const navigate = useNavigate()
  const create = useMutation<ABACPolicy, ApiError, ABACPolicyWrite>({
    mutationFn: (payload) => abacService.createPolicy(payload),
    onSuccess: (p) => navigate(`${ROUTES.ABAC_POLICIES}/${p.id}`),
  })

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <PageHeader
        icon={FilePlus2}
        title="New ABAC policy"
        description="Drafts never affect decisions until validated and published."
        backTo={ROUTES.ABAC_POLICIES}
        backLabel="Context policies overview"
      />
      <PolicyBuilder
        onSubmit={(payload) => create.mutate(payload)}
        submitting={create.isPending}
        error={create.isError ? create.error?.message ?? 'Could not create the policy.' : null}
        submitLabel="Create draft"
      />
    </div>
  )
}
