import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'

import { ROUTES } from '@/constants/routes'
import { abacService } from '@/services'
import type { ABACPolicy, ABACPolicyWrite, ApiError } from '@/types'
import { PolicyBuilder } from './components/PolicyBuilder'

/** Edit a policy (§33). Editing a published version creates a new draft version. */
export function EditABACPolicyPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const policy = useQuery({
    queryKey: ['abac-policy', id],
    queryFn: () => abacService.policy(id),
    enabled: !!id,
  })
  const update = useMutation<ABACPolicy, ApiError, ABACPolicyWrite>({
    mutationFn: (payload) => abacService.updatePolicy(id, payload),
    onSuccess: (p) => navigate(`${ROUTES.ABAC_POLICIES}/${p.id}`),
  })

  if (policy.isLoading) {
    return <div className="flex justify-center p-10"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
  }
  if (!policy.data) return <p className="p-6 text-sm text-muted-foreground">Policy not found.</p>

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Edit: {policy.data.name}</h1>
        <p className="text-sm text-muted-foreground">
          {policy.data.status === 'ACTIVE'
            ? 'This version is published and immutable — saving creates a new draft version.'
            : 'Editing the current draft.'}
        </p>
      </div>
      <PolicyBuilder
        initial={policy.data}
        onSubmit={(payload) => update.mutate(payload)}
        submitting={update.isPending}
        error={update.isError ? update.error?.message ?? 'Could not save the policy.' : null}
        submitLabel="Save changes"
      />
    </div>
  )
}
