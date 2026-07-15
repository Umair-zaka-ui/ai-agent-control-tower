import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus, ShieldCheck } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ROUTES } from '@/constants/routes'
import { abacService } from '@/services'
import type { ABACPolicy, ApiError, ID } from '@/types'
import { STATUS_STYLES } from './lib'

const STATUSES = ['', 'DRAFT', 'VALIDATED', 'ACTIVE', 'DISABLED', 'DEPRECATED', 'ARCHIVED']

/** ABAC policies (§33): the lifecycle-managed policy list. */
export function ABACPoliciesPage() {
  const qc = useQueryClient()
  const [status, setStatus] = useState('')
  const policies = useQuery({
    queryKey: ['abac-policies', status],
    queryFn: () => abacService.policies(status || undefined),
  })

  const invalidate = () => void qc.invalidateQueries({ queryKey: ['abac-policies'] })
  const publish = useMutation<unknown, ApiError, ID>({
    mutationFn: (id) => abacService.publishPolicy(id), onSuccess: invalidate,
  })
  const disable = useMutation<unknown, ApiError, ID>({
    mutationFn: (id) => abacService.disablePolicy(id), onSuccess: invalidate,
  })
  const archive = useMutation<unknown, ApiError, ID>({
    mutationFn: (id) => abacService.archivePolicy(id), onSuccess: invalidate,
  })
  const clone = useMutation<unknown, ApiError, ID>({
    mutationFn: (id) => abacService.clonePolicy(id), onSuccess: invalidate,
  })

  const actionsFor = (p: ABACPolicy) => {
    const actions: { label: string; onClick: () => void }[] = []
    if (p.status === 'DRAFT' || p.status === 'VALIDATED') {
      actions.push({ label: 'Publish', onClick: () => publish.mutate(p.id) })
    }
    if (p.status === 'ACTIVE') actions.push({ label: 'Disable', onClick: () => disable.mutate(p.id) })
    if (p.status !== 'ARCHIVED') actions.push({ label: 'Archive', onClick: () => archive.mutate(p.id) })
    actions.push({ label: 'Clone', onClick: () => clone.mutate(p.id) })
    return actions
  }
  const mutationError = publish.error ?? disable.error ?? archive.error ?? clone.error

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-foreground">ABAC policies</h1>
          <p className="text-sm text-muted-foreground">
            Context-aware authorization rules — drafted, validated, published, versioned.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select value={status} aria-label="Filter by status"
            onChange={(e) => setStatus(e.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1.5 text-sm">
            {STATUSES.map((s) => <option key={s} value={s}>{s || 'All statuses'}</option>)}
          </select>
          <Button asChild>
            <Link to={`${ROUTES.ABAC_POLICIES}/new`}><Plus className="h-4 w-4" /> New policy</Link>
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldCheck className="h-4 w-4" /> Policies
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {policies.isLoading ? (
            <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (policies.data ?? []).length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No policies yet.</p>
          ) : (
            <ul className="divide-y divide-border" data-testid="abac-policies-list">
              {(policies.data ?? []).map((p) => (
                <li key={p.id} className="flex flex-wrap items-center justify-between gap-3 p-3">
                  <div className="min-w-0">
                    <Link to={`${ROUTES.ABAC_POLICIES}/${p.id}`}
                      className="truncate text-sm font-medium text-foreground hover:underline">
                      {p.name}
                    </Link>
                    <p className="text-xs text-muted-foreground">
                      v{p.version} · {p.effect} · priority {p.priority} · {p.scope_type}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[p.status] ?? ''}`}>
                      {p.status}
                    </span>
                    {actionsFor(p).map((a) => (
                      <Button key={a.label} size="sm" variant="outline" onClick={a.onClick}>
                        {a.label}
                      </Button>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      {mutationError && <p className="text-xs text-destructive">{mutationError.message ?? 'Action failed.'}</p>}
    </div>
  )
}
