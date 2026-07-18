import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Share2, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/common'
import { ROUTES } from '@/constants/routes'
import { adminSessionService } from '@/services/authService'
import { resourceAuthzService } from '@/services'
import type { ApiError, ID, PrincipalType, ShareAccessLevel } from '@/types'
import { ResourcePicker } from './components/ResourcePicker'

const TARGETS: PrincipalType[] = ['USER', 'TEAM', 'DEPARTMENT', 'ORGANIZATION']
const LEVELS: ShareAccessLevel[] = ['READ', 'COMMENT', 'EXECUTE', 'EDIT', 'MANAGE']

/**
 * Resource sharing (Phase 4.3.4 §12, §21): share with users, teams, departments
 * or the whole organization at READ→MANAGE levels, with optional expiry.
 * Cross-organization sharing is denied server-side.
 */
export function ResourceSharingPage() {
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const resourceId = params.get('resource') ?? ''
  const [targetType, setTargetType] = useState<PrincipalType>('USER')
  const [targetId, setTargetId] = useState('')
  const [level, setLevel] = useState<ShareAccessLevel>('READ')

  const users = useQuery({ queryKey: ['org-users'], queryFn: () => adminSessionService.listUsers() })
  const shares = useQuery({
    queryKey: ['resource-shares', resourceId],
    queryFn: () => resourceAuthzService.shares(resourceId),
    enabled: !!resourceId,
  })

  const share = useMutation<unknown, ApiError>({
    mutationFn: () => resourceAuthzService.share(resourceId, {
      shared_with_type: targetType, shared_with_id: targetId, access_level: level,
    }),
    onSuccess: () => { setTargetId(''); void qc.invalidateQueries({ queryKey: ['resource-shares', resourceId] }) },
  })
  const modify = useMutation<unknown, ApiError, { shareId: ID; access_level: string }>({
    mutationFn: ({ shareId, access_level }) => resourceAuthzService.updateShare(resourceId, shareId, { access_level }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['resource-shares', resourceId] }),
  })
  const revoke = useMutation<unknown, ApiError, ID>({
    mutationFn: (shareId) => resourceAuthzService.revokeShare(resourceId, shareId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['resource-shares', resourceId] }),
  })
  const userLabel = (id: ID) => users.data?.find((u) => u.id === id)?.email ?? id
  const isExpired = (iso: string | null) => !!iso && new Date(iso).getTime() < Date.now()

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <PageHeader
        icon={Share2}
        title="Resource sharing"
        description="Explicit shares with users, teams and departments. Shares may expire; expired shares are ignored."
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
            <CardHeader><CardTitle className="text-base">Share this resource</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="space-y-1">
                  <Label htmlFor="share-ttype">Share with</Label>
                  <select id="share-ttype" value={targetType}
                    onChange={(e) => setTargetType(e.target.value as PrincipalType)}
                    className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                    {TARGETS.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="share-target">Target</Label>
                  {targetType === 'USER' ? (
                    <select id="share-target" value={targetId} onChange={(e) => setTargetId(e.target.value)}
                      className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                      <option value="">Select a user…</option>
                      {(users.data ?? []).map((u) => <option key={u.id} value={u.id}>{u.email}</option>)}
                    </select>
                  ) : (
                    <Input id="share-target" value={targetId} onChange={(e) => setTargetId(e.target.value)}
                      placeholder="Target id (UUID)" />
                  )}
                </div>
                <div className="space-y-1">
                  <Label htmlFor="share-level">Access level</Label>
                  <select id="share-level" value={level} onChange={(e) => setLevel(e.target.value as ShareAccessLevel)}
                    className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                    {LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
                  </select>
                </div>
              </div>
              <Button onClick={() => targetId && !share.isPending && share.mutate()}
                disabled={!targetId || share.isPending}>
                {share.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Share2 className="h-4 w-4" />} Share
              </Button>
              {share.isError && <p className="text-xs text-destructive">{share.error?.message ?? 'Could not share.'}</p>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-base">Active shares</CardTitle></CardHeader>
            <CardContent className="p-0">
              {shares.isLoading ? (
                <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
              ) : (shares.data ?? []).length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">This resource is not shared.</p>
              ) : (
                <ul className="divide-y divide-border" data-testid="shares-list">
                  {(shares.data ?? []).map((s) => (
                    <li key={s.id} className="flex flex-wrap items-center justify-between gap-3 p-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm text-foreground">
                          {s.shared_with_type === 'USER' ? userLabel(s.shared_with_id) : `${s.shared_with_type} ${s.shared_with_id}`}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {isExpired(s.expires_at) ? 'expired' : 'active'}
                          {s.expires_at ? ` · until ${new Date(s.expires_at).toLocaleDateString()}` : ''}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <select
                          value={s.access_level}
                          aria-label="Change access level"
                          onChange={(e) => modify.mutate({ shareId: s.id, access_level: e.target.value })}
                          className="rounded-md border border-border bg-background px-2 py-1 text-xs"
                        >
                          {LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
                        </select>
                        <Button size="sm" variant="ghost" disabled={revoke.isPending}
                          onClick={() => revoke.mutate(s.id)} aria-label="Revoke share">
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
          {(modify.isError || revoke.isError) && (
            <p className="text-xs text-destructive">
              {modify.error?.message ?? revoke.error?.message ?? 'Update failed.'}
            </p>
          )}
        </>
      )}
    </div>
  )
}
