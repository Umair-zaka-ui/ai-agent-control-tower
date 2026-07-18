import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { CheckCircle2, Loader2, Search, XCircle } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/common'
import { ROUTES } from '@/constants/routes'
import { adminSessionService } from '@/services/authService'
import { resourceAuthzService } from '@/services'
import type { ApiError, ID, ResourceAuthorizeResult } from '@/types'
import { ResourcePicker } from './components/ResourcePicker'

/**
 * Authorization Inspector (Phase 4.3.4 §21): security administrators simulate a
 * decision — identity + resource + permission in, ALLOW/DENY with the reason,
 * source, owner, visibility, scope and the evaluation steps out.
 */
export function AuthorizationInspectorPage() {
  const [params, setParams] = useSearchParams()
  const resourceId = params.get('resource') ?? ''
  const [identity, setIdentity] = useState('')
  const [permission, setPermission] = useState('')
  const [result, setResult] = useState<ResourceAuthorizeResult | null>(null)

  const users = useQuery({ queryKey: ['org-users'], queryFn: () => adminSessionService.listUsers() })
  const simulate = useMutation<ResourceAuthorizeResult, ApiError>({
    mutationFn: () => resourceAuthzService.authorize(resourceId, {
      permission: permission.trim(), identity_id: identity || null,
    }),
    onSuccess: (r) => setResult(r),
  })
  const userLabel = (id: ID | null) => (id && users.data?.find((u) => u.id === id)?.email) || id || '—'

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <PageHeader
        icon={Search}
        title="Authorization Inspector"
        description="Simulate an authorization decision for any identity, resource and permission."
        backTo={ROUTES.RES_PERMISSIONS}
        backLabel="Resources overview"
      />

      <Card>
        <CardHeader><CardTitle className="text-base">Simulation inputs</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1">
              <Label htmlFor="insp-identity">Identity</Label>
              <select id="insp-identity" value={identity} onChange={(e) => setIdentity(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                <option value="">Myself</option>
                {(users.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.email}</option>)}
              </select>
            </div>
            <ResourcePicker id="insp-resource" value={resourceId}
              onChange={(id) => setParams({ resource: id })} />
            <div className="space-y-1">
              <Label htmlFor="insp-permission">Permission</Label>
              <Input id="insp-permission" value={permission} onChange={(e) => setPermission(e.target.value)}
                placeholder="agent.update" />
            </div>
          </div>
          <Button onClick={() => resourceId && permission.trim() && !simulate.isPending && simulate.mutate()}
            disabled={!resourceId || !permission.trim() || simulate.isPending}>
            {simulate.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />} Evaluate
          </Button>
          {simulate.isError && (
            <p className="text-xs text-destructive">{simulate.error?.message ?? 'Evaluation failed.'}</p>
          )}
        </CardContent>
      </Card>

      {result && (
        <Card data-testid="inspector-result">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              {result.allowed ? (
                <><CheckCircle2 className="h-5 w-5 text-emerald-500" /> ALLOW</>
              ) : (
                <><XCircle className="h-5 w-5 text-destructive" /> DENY</>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
              <div><dt className="text-xs text-muted-foreground">Reason</dt><dd>{result.reason}</dd></div>
              <div><dt className="text-xs text-muted-foreground">Decided by</dt><dd>{result.source}</dd></div>
              <div>
                <dt className="text-xs text-muted-foreground">Inherited from</dt>
                <dd>{result.source_role ?? '—'}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">Resource owner</dt>
                <dd>
                  {result.owner_type === 'USER' ? userLabel(result.owner_id) : `${result.owner_type ?? '—'} ${result.owner_id ?? ''}`}
                </dd>
              </div>
              <div><dt className="text-xs text-muted-foreground">Visibility</dt><dd>{result.visibility ?? '—'}</dd></div>
              <div><dt className="text-xs text-muted-foreground">Scope</dt><dd>{result.scope ?? '—'}</dd></div>
            </dl>
            <div>
              <p className="text-xs text-muted-foreground">Evaluation steps</p>
              <ol className="mt-1 flex flex-wrap gap-1">
                {result.steps.map((s, i) => (
                  <li key={s} className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                    {i + 1}. {s}
                  </li>
                ))}
              </ol>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
