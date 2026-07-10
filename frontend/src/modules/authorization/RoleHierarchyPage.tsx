import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Loader2, Plus, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { authorizationService } from '@/services'
import type { ApiError, ID, RoleHierarchyEdge } from '@/types'

/**
 * Role hierarchy (Phase 4.3.1 §17, §22): a parent (senior) role inherits its
 * children's permissions. Cycles are rejected server-side.
 */
export function RoleHierarchyPage() {
  const qc = useQueryClient()
  const [parent, setParent] = useState('')
  const [child, setChild] = useState('')

  const roles = useQuery({ queryKey: ['authz-roles', ''], queryFn: () => authorizationService.listRoles() })
  const edges = useQuery({ queryKey: ['authz-hierarchy'], queryFn: () => authorizationService.listHierarchy() })

  const add = useMutation<RoleHierarchyEdge, ApiError>({
    mutationFn: () => authorizationService.createHierarchyEdge(parent, child),
    onSuccess: () => {
      setParent('')
      setChild('')
      void qc.invalidateQueries({ queryKey: ['authz-hierarchy'] })
    },
  })
  const remove = useMutation<void, ApiError, ID>({
    mutationFn: (id) => authorizationService.deleteHierarchyEdge(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['authz-hierarchy'] }),
  })

  const roleName = (id: ID) => (roles.data ?? []).find((r) => r.id === id)?.name ?? id

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Role hierarchy</h1>
        <p className="text-sm text-muted-foreground">
          A parent role inherits every permission of its children. The graph is kept acyclic.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Add an inheritance edge</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="h-parent">Parent (inherits)</Label>
              <select id="h-parent" value={parent} onChange={(e) => setParent(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                <option value="">Select a role…</option>
                {(roles.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="h-child">Child (inherited from)</Label>
              <select id="h-child" value={child} onChange={(e) => setChild(e.target.value)}
                className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm">
                <option value="">Select a role…</option>
                {(roles.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            </div>
          </div>
          <Button onClick={() => parent && child && !add.isPending && add.mutate()} disabled={!parent || !child || add.isPending}>
            {add.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Add edge
          </Button>
          {add.isError && (
            <p className="text-xs text-destructive" role="alert">{add.error?.message ?? 'Could not add the edge.'}</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {edges.isLoading ? (
            <div className="flex justify-center p-6" role="status" aria-label="Loading">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : (edges.data ?? []).length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No hierarchy edges yet.</p>
          ) : (
            <ul className="divide-y divide-border" data-testid="hierarchy-list">
              {(edges.data ?? []).map((e) => (
                <li key={e.id} className="flex items-center justify-between gap-3 p-3">
                  <p className="flex items-center gap-2 text-sm text-foreground">
                    <span className="font-medium">{roleName(e.parent_role_id)}</span>
                    <ArrowRight className="h-4 w-4 text-muted-foreground" />
                    <span>{roleName(e.child_role_id)}</span>
                  </p>
                  <Button size="sm" variant="ghost" disabled={remove.isPending} onClick={() => remove.mutate(e.id)} aria-label="Remove edge">
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
