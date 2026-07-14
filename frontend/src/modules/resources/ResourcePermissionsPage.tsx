import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Lock, Plus, ShieldQuestion } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ROUTES } from '@/constants/routes'
import { resourceAuthzService } from '@/services'
import type { ApiError, VisibilityLevel } from '@/types'

const VISIBILITIES: VisibilityLevel[] = ['PRIVATE', 'TEAM', 'DEPARTMENT', 'ORGANIZATION', 'PUBLIC_INTERNAL']

/**
 * Resource permissions overview (Phase 4.3.4 §20): the protected-resource
 * registry — register resources, see owner/visibility, change visibility, and
 * jump to the ACL / sharing / ownership / delegation / inspector pages.
 */
export function ResourcePermissionsPage() {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [type, setType] = useState('ai_agent')
  const [visibility, setVisibility] = useState<VisibilityLevel>('PRIVATE')

  const types = useQuery({ queryKey: ['resource-types'], queryFn: () => resourceAuthzService.resourceTypes() })
  const resources = useQuery({ queryKey: ['resources'], queryFn: () => resourceAuthzService.resources() })

  const register = useMutation<unknown, ApiError>({
    mutationFn: () => resourceAuthzService.register({ resource_type: type, name: name.trim(), visibility }),
    onSuccess: () => { setName(''); void qc.invalidateQueries({ queryKey: ['resources'] }) },
  })
  const setVis = useMutation<unknown, ApiError, { id: string; visibility: string }>({
    mutationFn: ({ id, visibility: v }) => resourceAuthzService.update(id, { visibility: v }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['resources'] }),
  })

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Resource permissions</h1>
        <p className="text-sm text-muted-foreground">
          Every protected resource with its owner and visibility. Manage fine-grained access via
          the <Link className="underline" to={ROUTES.RES_ACL}>ACL</Link>,{' '}
          <Link className="underline" to={ROUTES.RES_SHARING}>sharing</Link>,{' '}
          <Link className="underline" to={ROUTES.RES_OWNERSHIP}>ownership</Link> and{' '}
          <Link className="underline" to={ROUTES.RES_DELEGATION}>delegation</Link> pages, and verify
          decisions in the <Link className="underline" to={ROUTES.RES_INSPECTOR}>inspector</Link>.
        </p>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-base">Register a resource</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1">
              <Label htmlFor="res-name">Name</Label>
              <Input id="res-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Radiology triage agent" />
            </div>
            <div className="space-y-1">
              <Label htmlFor="res-type">Type</Label>
              <select id="res-type" value={type} onChange={(e) => setType(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                {(types.data ?? ['ai_agent']).map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="res-vis">Visibility</Label>
              <select id="res-vis" value={visibility} onChange={(e) => setVisibility(e.target.value as VisibilityLevel)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                {VISIBILITIES.map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
          </div>
          <Button onClick={() => !register.isPending && register.mutate()} disabled={register.isPending}>
            {register.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Register
          </Button>
          {register.isError && <p className="text-xs text-destructive">{register.error?.message ?? 'Could not register.'}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><Lock className="h-4 w-4" /> Protected resources</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {resources.isLoading ? (
            <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : (resources.data ?? []).length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No resources registered yet.</p>
          ) : (
            <ul className="divide-y divide-border" data-testid="resources-list">
              {(resources.data ?? []).map((r) => (
                <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 p-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm text-foreground">{r.name ?? r.resource_id}</p>
                    <p className="text-xs text-muted-foreground">
                      {r.resource_type} · {r.owner_type} owned · {r.status}
                      {r.policy?.length ? ` · ${r.policy.length} policy rule(s)` : ''}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <select
                      value={r.visibility}
                      aria-label={`Visibility of ${r.name ?? r.resource_id}`}
                      onChange={(e) => setVis.mutate({ id: r.id, visibility: e.target.value })}
                      className="rounded-md border border-border bg-background px-2 py-1 text-xs"
                    >
                      {VISIBILITIES.map((v) => <option key={v} value={v}>{v}</option>)}
                    </select>
                    <Button asChild size="sm" variant="outline">
                      <Link to={`${ROUTES.RES_INSPECTOR}?resource=${r.id}`} aria-label={`Inspect ${r.name ?? r.resource_id}`}>
                        <ShieldQuestion className="h-4 w-4" /> Inspect
                      </Link>
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      {setVis.isError && <p className="text-xs text-destructive">{setVis.error?.message ?? 'Could not update visibility.'}</p>}
    </div>
  )
}
