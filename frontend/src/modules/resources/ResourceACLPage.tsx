import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, Loader2, Plus, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/common'
import { ROUTES } from '@/constants/routes'
import { adminSessionService } from '@/services/authService'
import { resourceAuthzService } from '@/services'
import type { ACLEffect, ApiError, ID, PrincipalType } from '@/types'
import { ResourcePicker } from './components/ResourcePicker'

const PRINCIPALS: PrincipalType[] = ['USER', 'ROLE', 'TEAM', 'DEPARTMENT', 'ORGANIZATION', 'SERVICE_ACCOUNT']

/**
 * Resource ACL management (Phase 4.3.4 §10, §21): per-resource entries with
 * principal, permission, ALLOW/DENY effect and expiry. Explicit DENY always
 * overrides ALLOW; expired entries are ignored by the engine.
 */
export function ResourceACLPage() {
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const resourceId = params.get('resource') ?? ''
  const [search, setSearch] = useState('')
  const [principalType, setPrincipalType] = useState<PrincipalType>('USER')
  const [principalId, setPrincipalId] = useState('')
  const [permission, setPermission] = useState('')
  const [effect, setEffect] = useState<ACLEffect>('ALLOW')

  const users = useQuery({ queryKey: ['org-users'], queryFn: () => adminSessionService.listUsers() })
  const acl = useQuery({
    queryKey: ['resource-acl', resourceId],
    queryFn: () => resourceAuthzService.acl(resourceId),
    enabled: !!resourceId,
  })

  const add = useMutation<unknown, ApiError>({
    mutationFn: () => resourceAuthzService.addAclEntry(resourceId, {
      principal_type: principalType, principal_id: principalId, permission: permission.trim(), effect,
    }),
    onSuccess: () => {
      setPrincipalId(''); setPermission('')
      void qc.invalidateQueries({ queryKey: ['resource-acl', resourceId] })
    },
  })
  const toggle = useMutation<unknown, ApiError, { aclId: ID; effect: ACLEffect }>({
    mutationFn: ({ aclId, effect: e }) => resourceAuthzService.updateAclEntry(resourceId, aclId, { effect: e }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['resource-acl', resourceId] }),
  })
  const remove = useMutation<unknown, ApiError, ID>({
    mutationFn: (aclId) => resourceAuthzService.deleteAclEntry(resourceId, aclId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['resource-acl', resourceId] }),
  })

  const userLabel = (id: ID) => users.data?.find((u) => u.id === id)?.email ?? id
  const entries = useMemo(() => {
    const list = acl.data ?? []
    const q = search.trim().toLowerCase()
    if (!q) return list
    return list.filter((e) =>
      e.permission.toLowerCase().includes(q)
      || e.principal_type.toLowerCase().includes(q)
      || userLabel(e.principal_id).toLowerCase().includes(q),
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [acl.data, search, users.data])

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <PageHeader
        icon={KeyRound}
        title="Resource ACL"
        description="Explicit allow/deny entries per resource. Deny always wins; expired entries are ignored."
        backTo={ROUTES.RES_PERMISSIONS}
        backLabel="Resources overview"
      />

      <Card>
        <CardContent className="pt-4">
          <ResourcePicker value={resourceId} onChange={(id) => setParams({ resource: id })} />
        </CardContent>
      </Card>

      {resourceId && (
        <>
          <Card>
            <CardHeader><CardTitle className="text-base">Add ACL entry</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="grid gap-3 sm:grid-cols-4">
                <div className="space-y-1">
                  <Label htmlFor="acl-ptype">Principal type</Label>
                  <select id="acl-ptype" value={principalType}
                    onChange={(e) => setPrincipalType(e.target.value as PrincipalType)}
                    className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                    {PRINCIPALS.map((p) => <option key={p} value={p}>{p}</option>)}
                  </select>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="acl-principal">Principal</Label>
                  {principalType === 'USER' ? (
                    <select id="acl-principal" value={principalId} onChange={(e) => setPrincipalId(e.target.value)}
                      className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                      <option value="">Select a user…</option>
                      {(users.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.email}</option>)}
                    </select>
                  ) : (
                    <Input id="acl-principal" value={principalId} onChange={(e) => setPrincipalId(e.target.value)}
                      placeholder="Principal id (UUID)" />
                  )}
                </div>
                <div className="space-y-1">
                  <Label htmlFor="acl-permission">Permission</Label>
                  <Input id="acl-permission" value={permission} onChange={(e) => setPermission(e.target.value)}
                    placeholder="agent.update or *" />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="acl-effect">Effect</Label>
                  <select id="acl-effect" value={effect} onChange={(e) => setEffect(e.target.value as ACLEffect)}
                    className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                    <option value="ALLOW">ALLOW</option>
                    <option value="DENY">DENY</option>
                  </select>
                </div>
              </div>
              <Button onClick={() => principalId && permission.trim() && !add.isPending && add.mutate()}
                disabled={!principalId || !permission.trim() || add.isPending}>
                {add.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />} Add entry
              </Button>
              {add.isError && <p className="text-xs text-destructive">{add.error?.message ?? 'Could not add entry.'}</p>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="space-y-2">
              <CardTitle className="flex items-center gap-2 text-base"><KeyRound className="h-4 w-4" /> Entries</CardTitle>
              <Input value={search} onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by principal, permission or type…" aria-label="Search ACL entries" />
            </CardHeader>
            <CardContent className="p-0">
              {acl.isLoading ? (
                <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
              ) : entries.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">No ACL entries.</p>
              ) : (
                <ul className="divide-y divide-border" data-testid="acl-list">
                  {entries.map((e) => (
                    <li key={e.id} className="flex flex-wrap items-center justify-between gap-3 p-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm text-foreground">
                          {e.principal_type === 'USER' ? userLabel(e.principal_id) : `${e.principal_type} ${e.principal_id}`}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {e.permission}
                          {e.expires_at ? ` · expires ${new Date(e.expires_at).toLocaleDateString()}` : ''}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => toggle.mutate({ aclId: e.id, effect: e.effect === 'ALLOW' ? 'DENY' : 'ALLOW' })}
                          className={`rounded px-2 py-0.5 text-xs font-medium ${
                            e.effect === 'DENY' ? 'bg-destructive/10 text-destructive' : 'bg-emerald-500/10 text-emerald-600'
                          }`}
                          aria-label={`Toggle effect (currently ${e.effect})`}
                        >
                          {e.effect}
                        </button>
                        <Button size="sm" variant="ghost" disabled={remove.isPending}
                          onClick={() => remove.mutate(e.id)} aria-label="Delete ACL entry">
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
          {(toggle.isError || remove.isError) && (
            <p className="text-xs text-destructive">
              {toggle.error?.message ?? remove.error?.message ?? 'Update failed.'}
            </p>
          )}
        </>
      )}
    </div>
  )
}
