import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { authorizationService } from '@/services'
import type { ApiError, Permission, PermissionGroup } from '@/types'

/** Permissions catalog grouped by domain, with search + create (Phase 4.3.1 §22). */
export function PermissionsPage() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [code, setCode] = useState('')

  const permissions = useQuery({
    queryKey: ['authz-permissions'],
    queryFn: () => authorizationService.listPermissions(),
  })
  const groups = useQuery({
    queryKey: ['authz-permission-groups'],
    queryFn: () => authorizationService.listPermissionGroups(),
  })

  const create = useMutation<Permission, ApiError>({
    mutationFn: () => authorizationService.createPermission({ code: code.trim() }),
    onSuccess: () => {
      setCode('')
      void qc.invalidateQueries({ queryKey: ['authz-permissions'] })
    },
  })

  const grouped = useMemo(() => {
    const byId = new Map<string, PermissionGroup>((groups.data ?? []).map((g) => [g.id, g]))
    const q = search.trim().toLowerCase()
    const rows = (permissions.data ?? []).filter((p) => !q || p.code.toLowerCase().includes(q))
    const buckets = new Map<string, Permission[]>()
    for (const p of rows) {
      const key = p.group_id ? byId.get(p.group_id)?.display_name ?? 'Other' : 'Other'
      buckets.set(key, [...(buckets.get(key) ?? []), p])
    }
    return [...buckets.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [permissions.data, groups.data, search])

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Permissions</h1>
        <p className="text-sm text-muted-foreground">
          The <code>resource.action</code> catalog, grouped by domain (Phase 4.3.1).
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Add a permission</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              if (code.trim() && !create.isPending) create.mutate()
            }}
          >
            <div className="flex-1 space-y-1">
              <Label htmlFor="perm-code">Code (resource.action)</Label>
              <Input id="perm-code" value={code} onChange={(e) => setCode(e.target.value)} placeholder="report.export" />
            </div>
            <Button type="submit" disabled={!code.trim() || create.isPending}>
              {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Add
            </Button>
          </form>
          {create.isError && (
            <p className="mt-2 text-xs text-destructive" role="alert">
              {create.error?.message ?? 'Could not create the permission.'}
            </p>
          )}
        </CardContent>
      </Card>

      <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search permissions…" className="max-w-xs" />

      {permissions.isLoading ? (
        <div className="flex justify-center p-6" role="status" aria-label="Loading">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <div className="space-y-3" data-testid="permissions-groups">
          {grouped.map(([group, perms]) => (
            <Card key={group}>
              <CardHeader className="py-3">
                <CardTitle className="text-sm">{group} <span className="text-xs text-muted-foreground">({perms.length})</span></CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-1.5">
                {perms.map((p) => (
                  <span key={p.id} className="rounded bg-muted px-2 py-0.5 font-mono text-xs text-foreground" title={p.description ?? ''}>
                    {p.code}
                  </span>
                ))}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
