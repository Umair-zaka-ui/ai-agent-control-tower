import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, History, Loader2, Pencil, PlayCircle, XCircle } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { PageHeader } from '@/components/common'
import { ROUTES } from '@/constants/routes'
import { abacService } from '@/services'
import type { ABACValidationResult, ApiError } from '@/types'
import { STATUS_STYLES, policyToText } from './lib'

/** Policy details (§33): full readout, lifecycle actions, validation results. */
export function ABACPolicyDetailsPage() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const policy = useQuery({
    queryKey: ['abac-policy', id],
    queryFn: () => abacService.policy(id),
    enabled: !!id,
  })
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['abac-policy', id] })
    void qc.invalidateQueries({ queryKey: ['abac-policies'] })
  }
  const validate = useMutation<ABACValidationResult, ApiError>({
    mutationFn: () => abacService.validatePolicy(id), onSuccess: invalidate,
  })
  const publish = useMutation<unknown, ApiError>({
    mutationFn: () => abacService.publishPolicy(id), onSuccess: invalidate,
  })
  const disable = useMutation<unknown, ApiError>({
    mutationFn: () => abacService.disablePolicy(id), onSuccess: invalidate,
  })

  if (policy.isLoading) {
    return <div className="flex justify-center p-10"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
  }
  const p = policy.data
  if (!p) return <p className="p-6 text-sm text-muted-foreground">Policy not found.</p>
  const mutationError = validate.error ?? publish.error ?? disable.error

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <PageHeader
        title={p.name}
        description={`v${p.version} · ${p.effect} · priority ${p.priority} · ${p.combining_algorithm} · ${p.scope_type}`}
        backTo={ROUTES.ABAC_POLICIES}
        backLabel="Context policies overview"
        actions={
          <>
            <span className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[p.status] ?? ''}`}>
              {p.status}
            </span>
          {(p.status === 'DRAFT' || p.status === 'VALIDATED') && (
            <>
              <Button size="sm" variant="outline" onClick={() => validate.mutate()}
                disabled={validate.isPending}>Validate</Button>
              <Button size="sm" onClick={() => publish.mutate()} disabled={publish.isPending}>
                Publish
              </Button>
            </>
          )}
          {p.status === 'ACTIVE' && (
            <Button size="sm" variant="outline" onClick={() => disable.mutate()}
              disabled={disable.isPending}>Disable</Button>
          )}
          <Button asChild size="sm" variant="outline">
            <Link to={`${ROUTES.ABAC_POLICIES}/${p.id}/edit`}><Pencil className="h-4 w-4" /> Edit</Link>
          </Button>
          <Button asChild size="sm" variant="outline">
            <Link to={`${ROUTES.ABAC_POLICIES}/${p.id}/versions`}><History className="h-4 w-4" /> Versions</Link>
          </Button>
            <Button asChild size="sm" variant="outline">
              <Link to={`${ROUTES.ABAC_SIMULATOR}?policy=${p.id}`}><PlayCircle className="h-4 w-4" /> Simulate</Link>
            </Button>
          </>
        }
      />

      {validate.data && (
        <Card data-testid="validation-result">
          <CardContent className="pt-4">
            {validate.data.valid ? (
              <p className="flex items-center gap-2 text-sm text-emerald-600">
                <CheckCircle2 className="h-4 w-4" /> Policy is valid.
              </p>
            ) : (
              <div className="space-y-1">
                <p className="flex items-center gap-2 text-sm text-destructive">
                  <XCircle className="h-4 w-4" /> Validation failed:
                </p>
                <ul className="list-inside list-disc text-xs text-destructive">
                  {validate.data.errors.map((e, i) => <li key={i}>{e.message}</li>)}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle className="text-base">Human-readable</CardTitle></CardHeader>
        <CardContent>
          <pre className="whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">{policyToText(p)}</pre>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Definition</CardTitle></CardHeader>
        <CardContent>
          <pre className="max-h-96 overflow-auto rounded-md bg-muted p-3 text-xs">
            {JSON.stringify({ target: p.target, conditions: p.conditions,
                              obligations: p.obligations }, null, 2)}
          </pre>
        </CardContent>
      </Card>

      {mutationError && <p className="text-xs text-destructive">{mutationError.message ?? 'Action failed.'}</p>}
      {publish.isSuccess && (
        <Button variant="link" onClick={() => navigate(ROUTES.ABAC_POLICIES)}>Back to policies</Button>
      )}
    </div>
  )
}
